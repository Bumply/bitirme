"""
Wheelchair BCI — Decoder (Coral) Ana Çalıştırma Script'i

Görevleri:
1. Donanımı algıla (Coral ise SPI'dan, PC ise simüle veriden oku)
2. Modeli yükle (TFLite veya PyTorch)
3. Modülleri (DSP, Filtre, Sender, Smoother) bir araya getir
4. 3 paralel thread'de sistemi çalıştır:
   - Veri okuma + filtreleme (250Hz)
   - Inference (yarm saniyede bir)
   - Kalibrasyon dinleyici (sürekli)
"""

import time
import threading
from datetime import datetime
import numpy as np

# Kendi yazdığımız modülleri import ediyoruz
from wheelchair_bci.config import FS, N_CH, BUFFER_SIZE, DSP_INTERVAL, CLASS_NAMES
from wheelchair_bci.decoder.dsp import FilterChain
from wheelchair_bci.decoder.inference import load_engine
from wheelchair_bci.decoder.smoother import CommandSmoother
from wheelchair_bci.decoder.wifi_sender import CommandSender
from wheelchair_bci.decoder.online_adapter import OnlineAdapter
from wheelchair_bci.decoder.calibration_recorder import CalibrationRecorder
from wheelchair_bci.decoder.ads1299 import is_coral
from wheelchair_bci.decoder.artifact_reject import ArtifactRejector
from wheelchair_bci.decoder.lead_off import LeadOffDetector
from wheelchair_bci.decoder.ota_receiver import OTAReceiver
from wheelchair_bci.tee_logger import TeeLogger


# ==============================================================================
# PAYLAŞIMLI DURUM (Thread'ler Arası Köprü)
# ==============================================================================

class SharedState:
    """
    Okuma thread'i (250Hz) ile Inference thread'i (2Hz) arasında
    filtrelenmiş EEG verisini taşıyan thread-safe ring buffer.
    """
    def __init__(self, buffer_size: int = BUFFER_SIZE):
        self.buffer_size = buffer_size
        self.buffer = np.zeros((buffer_size, N_CH), dtype=np.float64)
        self.idx = 0
        self.count = 0
        self.lock = threading.Lock()

    def append(self, sample: np.ndarray):
        """Her 4ms'de filtrelenmiş 1 örneği buffer'a yazar."""
        with self.lock:
            self.buffer[self.idx] = sample
            self.idx = (self.idx + 1) % self.buffer_size
            self.count += 1

    @property
    def is_ready(self) -> bool:
        """Buffer ilk 1 saniyelik veriyle doldu mu?"""
        with self.lock:
            return self.count >= self.buffer_size

    def snapshot(self) -> np.ndarray:
        """İnference için son 1 saniyelik buffer'ı zaman sıralı olarak verir."""
        with self.lock:
            # Ring buffer'ı düzelt (örneğin idx 50 ise, önce 50-250 arası, sonra 0-50 arası)
            return np.roll(self.buffer, -self.idx, axis=0)


# ==============================================================================
# THREAD 1: OKUMA VE FİLTRELEME
# ==============================================================================

def run_stream_thread_hardware(ads_reader, filter_chain, shared_state, stop_event):
    """Coral üzerinde ADS1299 çipinden gerçek veri okur."""
    print("[THREAD] Gerçek donanım akışı başladı (250Hz)")
    try:
        while not stop_event.is_set():
            # 1. Ham veriyi oku (DRDY pinini bekler → 4ms)
            sample_raw = ads_reader.read_sample()
            
            # 2. Notch + Bandpass filtre uygula
            sample_filt = filter_chain.process_sample(sample_raw)
            
            # 3. Buffer'a yaz
            shared_state.append(sample_filt)
            
    except Exception as e:
        print(f"[THREAD] Donanım okuma hatası: {e}")
    finally:
        stop_event.set()


def run_stream_thread_sitl(shared_state, filter_chain, stop_event, duration=60):
    """Laptop/PC testleri için GDF dosyasından simüle veri okur."""
    print("[THREAD] SITL Simülasyon akışı başladı (GDF dosyası)")
    
    # GDF okuma modülünü yükle (sadece simülasyonda)
    import mne
    from wheelchair_bci.config import PROJECT_ROOT, CHANNELS
    
    gdf_path = PROJECT_ROOT / "Data" / "A01T.gdf"
    if not gdf_path.exists():
        print(f"[ERROR] Simülasyon verisi bulunamadı: {gdf_path}")
        stop_event.set()
        return

    # Veriyi yükle ve volt'a çevir
    raw = mne.io.read_raw_gdf(str(gdf_path), preload=True, verbose=False)
    eeg_data = raw.get_data()  # Şekil: (22 kanal, N örnek)
    
    # İlk 8 kanalı eşleştir ve volt yap (MNE verisi mikrovolt veya volt olabilir, duruma göre ayarlanır) # pylint: disable=line-too-long
    eeg_data = eeg_data[:8, :] 
    
    n_samples = min(duration * FS, eeg_data.shape[1])
    
    # Simüle okuma döngüsü
    for i in range(n_samples):
        if stop_event.is_set():
            break
            
        sample_raw = eeg_data[:, i] # (8,)
        
        # Filtrele
        sample_filt = filter_chain.process_sample(sample_raw)
        
        # Buffer'a ekle
        shared_state.append(sample_filt)
        
        # Gerçek zamanı simüle et (saniyede 250 okuma = her okuma 4ms)
        time.sleep(1.0 / FS)
        
    print("[THREAD] Simülasyon bitti")
    stop_event.set()


# ==============================================================================
# THREAD 2: INFERENCE (YARIM SANİYEDE BİR)
# ==============================================================================

def run_inference_thread(shared_state, stop_event, engine, smoother, 
                         sender, adapter, rejector, lead_off):
    """
    Saniyede 2 kere buffer'dan veriyi çeker, tahminde bulunur, 
    sonucu yumuşatır ve UDP üzerinden Pi5'e gönderir.
    """
    print("[THREAD] Inference başladı (2Hz)")
    
    # Buffer'ın dolması için ilk saniyeyi bekle
    while not shared_state.is_ready and not stop_event.is_set():
        time.sleep(0.1)

    while not stop_event.is_set():
        start_t = time.time()
        
        # 1. Son 1 saniyelık filtreleınmiş veriyi al
        window = shared_state.snapshot()  # (250, 8)
        
        # 2. Lead-off kontrolü (elektrot kopma)
        off_channels = lead_off.check_simulated(window)
        is_safe, loff_reason = lead_off.is_safe()
        if not is_safe:
            sender.send("S", 0.0)
            print(f"[⚠ LEAD-OFF] {loff_reason} | "
                  f"Kopuk kanallar: {off_channels}")
            elapsed = time.time() - start_t
            sleep_t = max(0.001, DSP_INTERVAL - elapsed)
            time.sleep(sleep_t)
            continue
        
        # 3. Artifact kontrolü (göz kırpma / kas hareketi)
        is_clean, artifact_reason = rejector.check(window)
        
        if not is_clean:
            # Kirlenmiş pencere — inference yapma, güvenli DUR gönder
            sender.send("S", 0.0)
            print(f"[⚠ ARTIFACT] {artifact_reason} | "
                  f"Red oranı: {rejector.rejection_rate:.1f}%")
            elapsed = time.time() - start_t
            sleep_t = max(0.001, DSP_INTERVAL - elapsed)
            time.sleep(sleep_t)
            continue
        
        # 4. Modeli çalıştır
        command, confidence, probs = engine.predict(window)
        
        # 5. Micro fine-tune tamponuna ekle (şartlar uygunsa)
        adapter.accumulate(window, command, confidence)
        
        # 6. Tahmini yumuşat (jitter önleme)
        final_cmd, reason = smoother.update(command, confidence)
        
        # 7. Pi5'e paket gönder
        sender.send(final_cmd, confidence)
        
        # Ekrana logla
        prob_str = " ".join([f"{CLASS_NAMES[i]}:{probs[i]:.2f}" for i in range(4)])
        print(f"[{final_cmd}] conf={confidence:.2f} | {reason:<8} | raw={command} | {prob_str}")
        
        # 6. Bir sonraki analize kadar uyu (DSP_INTERVAL = 0.5s)
        # İşlem süresini bekleme süresinden çıkar ki zaman kayması olmasın
        elapsed = time.time() - start_t
        sleep_t = max(0.001, DSP_INTERVAL - elapsed)
        time.sleep(sleep_t)


# ==============================================================================
# ANA INITIATOR KODU
# ==============================================================================

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    running_on_coral = is_coral()

    # Tüm çıktıları log dosyasına kaydet
    logger = TeeLogger("decoder")

    print("=" * 60)
    print("  WHEELCHAIR BCI -- DECODER | CORAL GİRİŞ NOKTASI")
    print(f"  Donanım: {'CORAL' if running_on_coral else 'SITL (Simülasyon)'}")
    print(f"  Zaman:   {timestamp}")
    print("=" * 60)

    # 1. Modeli yükle (Ağaç altından otomatik)
    try:
        engine = load_engine()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return

    # 2. Bileşenleri başlat
    filter_chain = FilterChain()
    shared_state = SharedState(BUFFER_SIZE)
    smoother = CommandSmoother(threshold=getattr(engine, "dynamic_threshold", None))
    sender = CommandSender()
    adapter = OnlineAdapter(engine)
    rejector = ArtifactRejector()
    lead_off = LeadOffDetector()
    stop_event = threading.Event()

    # OTA hot-swap callback
    engine_ref = [engine]  # mutable container for closure
    def on_ota_model(new_path):
        new_engine = load_engine(new_path)
        engine_ref[0] = new_engine
        print(f"[OTA] ✅ Inference motoru değiştirildi: {new_path.name}")

    ota = OTAReceiver(on_model_received=on_ota_model)
    ota.start()
    
    print("\n[INIT] Tüm bileşenler başarıyla oluşturuldu.\n")

    # 3. Thread'leri yapılandır
    if running_on_coral:
        from wheelchair_bci.ads1299 import ADS1299Reader
        ads_reader = ADS1299Reader()
        stream_thread = threading.Thread(
            target=run_stream_thread_hardware,
            args=(ads_reader, filter_chain, shared_state, stop_event),
            daemon=True,
        )
    else:
        stream_thread = threading.Thread(
            target=run_stream_thread_sitl,
            args=(shared_state, filter_chain, stop_event, 6000), # 100 dakika (6000sn) boyunca simülasyon yap
            daemon=True,
        )

    infer_thread = threading.Thread(
        target=run_inference_thread,
        args=(shared_state, stop_event, engine, smoother, sender, adapter, rejector, lead_off),
        daemon=True,
    )
    
    cal_recorder = CalibrationRecorder(shared_state, stop_event)
    cal_thread = threading.Thread(
        target=cal_recorder.run,
        daemon=True,
        name="CalibrationThread",
    )

    # 4. Sistemi ateşle!
    stream_thread.start()
    infer_thread.start()
    cal_thread.start()

    # 5. Programı hayatta tut, kapanışı bekle
    try:
        stream_thread.join()
    except KeyboardInterrupt:
        print("\n[MAIN] Kapatılıyor (Ctrl+C)...")
        stop_event.set()

    # Kapanış beklemesi
    infer_thread.join(timeout=3.0)
    cal_thread.join(timeout=2.0)

    # Temizlik
    sender.close()
    if running_on_coral:
        ads_reader.close()

    print("[MAIN] Decoder kapatıldı.")
    logger.close()


if __name__ == "__main__":
    main()
