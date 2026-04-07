"""
Wheelchair BCI — Offline Veri Toplama Aracı (Data Logger)

Kullanıcıya ekranda yönlü cue'lar (⬆️ ⬅️ ➡️ ⏹️) gösterir.
O sırada EEG verisini kaydeder. Kayıt bitince .npz dosyası üretir.
Bu dosya ile decoder_training.py --personal çalıştırılarak
kullanıcıya özel model eğitilebilir.

Kullanım:
    python -m wheelchair_bci.offline_logger

Donanım:
    - Coral (ADS1299) → gerçek EEG kaydı
    - PC/Mac          → GDF dosyasından simüle kayıt (test için)
"""

import time
import random
import threading
from pathlib import Path
from datetime import datetime

import numpy as np

from wheelchair_bci.config import (
    FS, N_CH, CHANNELS, CLASS_NAMES,
    BUFFER_SIZE, CAL_DATA_DIR, PROJECT_ROOT,
    CAL_FIXATION_S, CAL_IMAGERY_S, CAL_REST_S,
    CAL_TRIALS_PER_CLASS,
)
from wheelchair_bci.decoder.dsp import FilterChain
from wheelchair_bci.decoder.ads1299 import is_coral

# NiceGUI import
from nicegui import ui, app


# ══════════════════════════════════════════════════
# 1. EEG VERİ KAYNAK KATMANI
# ══════════════════════════════════════════════════

class EEGSource:
    """
    EEG veri kaynağı soyutlaması.
    Donanım varsa ADS1299'dan, yoksa GDF dosyasından veri okur.
    """

    def __init__(self):
        self.filter_chain = FilterChain()
        self.running = False
        self._buffer = np.zeros((BUFFER_SIZE, N_CH), dtype=np.float64)
        self._idx = 0
        self._count = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

        # Simülasyon için GDF verisi
        self._sim_data = None
        self._sim_pos = 0

    def start(self):
        """EEG okumayı arka plan thread'inde başlatır."""
        self._stop_event.clear()
        self.running = True

        if is_coral():
            self._thread = threading.Thread(target=self._read_hardware, daemon=True)
        else:
            self._load_sim_data()
            self._thread = threading.Thread(target=self._read_simulation, daemon=True)

        self._thread.start()

    def stop(self):
        """EEG okumayı durdurur."""
        self._stop_event.set()
        self.running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _load_sim_data(self):
        """GDF dosyasından simüle veri yükler."""
        import mne
        gdf_path = PROJECT_ROOT / "Data" / "A01T.gdf"
        if not gdf_path.exists():
            print(f"[LOGGER] HATA: Simülasyon verisi bulunamadı: {gdf_path}")
            return
        raw = mne.io.read_raw_gdf(str(gdf_path), preload=True, verbose=False)
        self._sim_data = raw.get_data()[:8, :]  # İlk 8 kanal
        self._sim_pos = 0
        print(f"[LOGGER] Simülasyon verisi yüklendi: {self._sim_data.shape[1]} örnek")

    def _read_simulation(self):
        """GDF'ten simüle EEG okur (250Hz hızında)."""
        if self._sim_data is None:
            return
        n_total = self._sim_data.shape[1]
        while not self._stop_event.is_set():
            sample = self._sim_data[:, self._sim_pos % n_total]
            filtered = self.filter_chain.process_sample(sample)
            with self._lock:
                self._buffer[self._idx] = filtered
                self._idx = (self._idx + 1) % BUFFER_SIZE
                self._count += 1
            self._sim_pos += 1
            time.sleep(1.0 / FS)

    def _read_hardware(self):
        """ADS1299'dan gerçek EEG okur."""
        from wheelchair_bci.decoder.ads1299 import ADS1299Reader
        reader = ADS1299Reader()
        try:
            while not self._stop_event.is_set():
                sample = reader.read_sample()
                filtered = self.filter_chain.process_sample(sample)
                with self._lock:
                    self._buffer[self._idx] = filtered
                    self._idx = (self._idx + 1) % BUFFER_SIZE
                    self._count += 1
        finally:
            reader.close()

    def get_window(self):
        """
        Son 1 saniyelik filtrelenmiş EEG verisini döndürür.
        Buffer henüz dolmadıysa None döner.
        """
        with self._lock:
            if self._count < BUFFER_SIZE:
                return None
            # Ring buffer'ı zaman sıralı hale getir
            return np.roll(self._buffer.copy(), -self._idx, axis=0)


# ══════════════════════════════════════════════════
# 2. PROTOKOL MOTORU
# ══════════════════════════════════════════════════

class ProtocolEngine:
    """
    Kalibrasyon cue protokolünü yönetir.

    Her deneme: FIXATION (2s) → IMAGERY (4s) → REST (2s) = 8s
    4 sınıf × 25 deneme = 100 deneme ≈ 13 dakika

    Imagery fazında EEG pencerelerini toplar.
    """

    def __init__(self, eeg_source: EEGSource,
                 trials_per_class: int = CAL_TRIALS_PER_CLASS):
        self.eeg = eeg_source
        self.trials_per_class = trials_per_class

        # Deneme listesi (rastgele karıştırılmış)
        self.trials = []
        for cls_idx, cls_name in enumerate(CLASS_NAMES):
            self.trials.extend([(cls_idx, cls_name)] * trials_per_class)
        random.shuffle(self.trials)
        self.total_trials = len(self.trials)

        # Kaydedilen veriler
        self.windows = []   # EEG pencereleri
        self.labels = []    # Sınıf etiketleri (int)

        # Durum
        self.current_trial = 0
        self.current_phase = "idle"     # idle, fixation, imagery, rest, done
        self.current_cue = ""           # "F", "L", "R", "S"
        self.phase_progress = 0.0       # 0.0 - 1.0  (faz ilerleme çubuğu)
        self.running = False
        self._stop_event = threading.Event()

    def start(self, on_update=None):
        """Protokolü arka plan thread'inde başlatır."""
        self.running = True
        self._stop_event.clear()
        self._on_update = on_update
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def stop(self):
        """Protokolü durdurur."""
        self._stop_event.set()
        self.running = False

    def _notify(self):
        """UI güncelleme callback'ini çağırır."""
        if self._on_update:
            self._on_update()

    def _run(self):
        """Ana protokol döngüsü."""
        print(f"[LOGGER] Protokol başladı: {self.total_trials} deneme")

        for i, (cls_idx, cls_name) in enumerate(self.trials):
            if self._stop_event.is_set():
                break

            self.current_trial = i + 1
            self.current_cue = cls_name

            # ── FIXATION ──
            self.current_phase = "fixation"
            self._notify()
            if not self._wait_with_progress(CAL_FIXATION_S):
                break

            # ── IMAGERY (VERİ KAYDI) ──
            self.current_phase = "imagery"
            self._notify()

            # Imagery fazı boyunca her 0.5s'de bir pencere kaydet
            imagery_start = time.time()
            while time.time() - imagery_start < CAL_IMAGERY_S:
                if self._stop_event.is_set():
                    break

                elapsed = time.time() - imagery_start
                self.phase_progress = min(elapsed / CAL_IMAGERY_S, 1.0)
                self._notify()

                # EEG penceresi al ve kaydet
                window = self.eeg.get_window()
                if window is not None:
                    self.windows.append(window)
                    self.labels.append(cls_idx)

                time.sleep(0.5)  # Her yarım saniyede bir pencere

            # ── REST ──
            self.current_phase = "rest"
            self._notify()
            if not self._wait_with_progress(CAL_REST_S):
                break

        # ── BİTTİ ──
        self.current_phase = "done"
        self.running = False
        self._notify()
        print(f"[LOGGER] Protokol bitti: {len(self.windows)} pencere kaydedildi")

    def _wait_with_progress(self, duration: float) -> bool:
        """Beklerken ilerleme çubuğunu günceller."""
        start = time.time()
        while time.time() - start < duration:
            if self._stop_event.is_set():
                return False
            elapsed = time.time() - start
            self.phase_progress = min(elapsed / duration, 1.0)
            self._notify()
            time.sleep(0.1)
        self.phase_progress = 1.0
        return True

    def save(self) -> Path:
        """Kaydedilen veriyi .npz dosyasına yazar."""
        CAL_DATA_DIR.mkdir(parents=True, exist_ok=True)

        # EEG pencerelerini 4D'ye çevir: (n, 250, 8) → (n, 1, 8, 250)
        X_raw = np.array(self.windows)                          # (n, 250, 8)
        X = X_raw.transpose(0, 2, 1)[:, np.newaxis, :, :]      # (n, 1, 8, 250)
        X = X.astype(np.float32) * 1e6                          # V → µV

        y = np.array(self.labels, dtype=np.int64)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = CAL_DATA_DIR / f"personal_{timestamp}.npz"

        np.savez(save_path, X=X, y=y, channels=CHANNELS, fs=FS,
                 class_names=CLASS_NAMES)

        # Sınıf dağılımını logla
        dist = {CLASS_NAMES[i]: int(np.sum(y == i)) for i in range(4)}
        print(f"[LOGGER] Kaydedildi: {save_path.name}")
        print(f"  Shape: X={X.shape}, y={y.shape}")
        print(f"  Dağılım: {dist}")

        return save_path


# ══════════════════════════════════════════════════
# 3. NiceGUI ARAYÜZÜ
# ══════════════════════════════════════════════════

CUE_ARROWS = {
    "F": ("⬆", "İLERİ", "#22c55e"),        # Yeşil
    "L": ("⬅", "SOL",    "#3b82f6"),        # Mavi
    "R": ("➡", "SAĞ",    "#f59e0b"),        # Turuncu
    "S": ("⏹", "DUR",    "#ef4444"),        # Kırmızı
}

PHASE_LABELS = {
    "idle":     ("⏸️ Hazır", "Başlamak için aşağıdaki butona bas"),
    "fixation": ("➕ ODAKLAN", "Ekranın ortasına bak, gözlerini kırpma"),
    "imagery":  ("🧠 HAYAL ET", "Aşağıdaki yönü düşün!"),
    "rest":     ("😌 DİNLEN", "Rahatla, gözlerini kırpabilirsin"),
    "done":     ("✅ TAMAMLANDI", "Veri başarıyla kaydedildi!"),
}


# Global nesneler
eeg_source: EEGSource | None = None
protocol: ProtocolEngine | None = None
update_timer = None


def build_logger_ui():
    """Veri toplama arayüzünü oluşturur."""
    global eeg_source, protocol

    # ── Sayfa stili ──
    ui.add_head_html("""
    <style>
        body { background: #0a0a0a !important; }
        .cue-arrow {
            font-size: 120px;
            line-height: 1;
            animation: pulse 1s ease-in-out infinite;
        }
        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.1); opacity: 0.85; }
        }
        .phase-fixation { color: #facc15; }
        .phase-imagery  { color: #22d3ee; }
        .phase-rest     { color: #94a3b8; }
        .big-plus {
            font-size: 100px;
            color: #facc15;
            line-height: 1;
        }
    </style>
    """)

    # ── Üst başlık ──
    with ui.header().classes("bg-gray-900 items-center justify-between"):
        ui.label("🧠 BCI Veri Toplama").classes("text-xl font-bold text-white")
        status_badge = ui.badge("SİMÜLASYON" if not is_coral() else "DONANIM",
                                color="blue" if not is_coral() else "green")

    # ── Ana alan ──
    with ui.column().classes("w-full items-center justify-center mt-8"):

        # İlerleme bilgisi
        with ui.row().classes("gap-8 mb-4"):
            trial_label = ui.label("Deneme: 0 / 0").classes(
                "text-lg text-gray-400")
            window_label = ui.label("Pencere: 0").classes(
                "text-lg text-gray-400")

        # Faz başlığı
        phase_title = ui.label("⏸️ Hazır").classes(
            "text-3xl font-bold text-white mt-4")
        phase_desc = ui.label("Başlamak için aşağıdaki butona bas").classes(
            "text-lg text-gray-400 mb-4")

        # Cue alanı (büyük ok veya + işareti)
        with ui.card().classes(
            "w-80 h-80 flex items-center justify-center "
            "bg-gray-900 border border-gray-700 rounded-2xl"
        ):
            cue_display = ui.label("").classes("cue-arrow")

        # İlerleme çubuğu
        progress_bar = ui.linear_progress(value=0, size="12px").classes(
            "w-80 mt-4 rounded-lg"
        ).props("color='cyan'")

        # Sınıf etiketi
        cue_name_label = ui.label("").classes(
            "text-2xl font-bold mt-2 text-gray-300")

        # Toplam ilerleme
        ui.label("Toplam İlerleme").classes("text-sm text-gray-500 mt-6")
        total_progress = ui.linear_progress(value=0, size="8px").classes(
            "w-96 rounded-lg"
        ).props("color='green'")

    # ── Kontrol butonları ──
    with ui.row().classes("mt-6 gap-4"):
        start_btn = ui.button("▶️  BAŞLAT", on_click=lambda: do_start()) \
            .props("color='positive' size='lg'").classes("px-8")
        stop_btn = ui.button("⏹  DURDUR", on_click=lambda: do_stop()) \
            .props("color='negative' size='lg'").classes("px-8")
        stop_btn.set_visibility(False)

    # ── Sonuç kartı (gizli, bitince çıkar) ──
    with ui.card().classes(
        "w-96 mt-6 bg-gray-800 border border-green-600 rounded-xl p-6"
    ) as result_card:
        result_card.set_visibility(False)
        result_title = ui.label("").classes("text-xl font-bold text-green-400")
        result_detail = ui.label("").classes("text-gray-300 mt-2")
        train_btn = ui.button(
            "🚀  Modeli Eğit (--personal)",
            on_click=lambda: ui.notify(
                "Terminalde çalıştır:\npython -m wheelchair_bci.decoder_training --personal",
                type="info", timeout=10000,
            ),
        ).props("color='primary' size='lg'").classes("mt-4 w-full")

    # ── UI güncelleme fonksiyonu ──
    def refresh_ui():
        if protocol is None:
            return

        p = protocol
        phase = p.current_phase

        # İlerleme
        trial_label.set_text(f"Deneme: {p.current_trial} / {p.total_trials}")
        window_label.set_text(f"Pencere: {len(p.windows)}")

        # Faz bilgisi
        title, desc = PHASE_LABELS.get(phase, ("", ""))
        phase_title.set_text(title)
        phase_desc.set_text(desc)

        # Cue görseli
        if phase == "fixation":
            cue_display.set_text("+")
            cue_display.classes(replace="cue-arrow big-plus phase-fixation")
            cue_name_label.set_text("")
        elif phase == "imagery" and p.current_cue in CUE_ARROWS:
            arrow, name, color = CUE_ARROWS[p.current_cue]
            cue_display.set_text(arrow)
            cue_display.classes(replace="cue-arrow phase-imagery")
            cue_display.style(f"color: {color}")
            cue_name_label.set_text(name)
        elif phase == "rest":
            cue_display.set_text("~")
            cue_display.classes(replace="cue-arrow phase-rest")
            cue_name_label.set_text("")
        elif phase == "done":
            cue_display.set_text("✅")
            cue_display.classes(replace="cue-arrow")
            cue_name_label.set_text("")
        elif phase == "idle":
            cue_display.set_text("")
            cue_name_label.set_text("")

        # İlerleme çubukları
        progress_bar.set_value(p.phase_progress)
        if p.total_trials > 0:
            total_progress.set_value(p.current_trial / p.total_trials)

        # Bitince sonuç kartı
        if phase == "done" and not result_card.visible:
            save_path = p.save()
            dist = {CLASS_NAMES[i]: int(np.sum(np.array(p.labels) == i))
                    for i in range(4)}
            result_card.set_visibility(True)
            result_title.set_text(
                f"✅ {len(p.windows)} pencere kaydedildi!")
            result_detail.set_text(
                f"Dosya: {save_path.name}\nDağılım: {dist}")
            start_btn.set_visibility(True)
            stop_btn.set_visibility(False)

    # ── Buton aksiyonları ──
    def do_start():
        global eeg_source, protocol
        result_card.set_visibility(False)
        start_btn.set_visibility(False)
        stop_btn.set_visibility(True)

        eeg_source = EEGSource()
        eeg_source.start()

        # Buffer'ın dolması için kısa bekle
        time.sleep(1.2)

        protocol = ProtocolEngine(eeg_source)
        protocol.start(on_update=None)

    def do_stop():
        global eeg_source, protocol
        if protocol:
            protocol.stop()
        if eeg_source:
            eeg_source.stop()
        start_btn.set_visibility(True)
        stop_btn.set_visibility(False)

    # ── Zamanlayıcı: 200ms'de bir UI güncelle ──
    ui.timer(0.2, callback=refresh_ui)


# ══════════════════════════════════════════════════
# 4. ANA GİRİŞ NOKTASI
# ══════════════════════════════════════════════════

@ui.page("/")
def index():
    build_logger_ui()


def main():
    hardware = "CORAL (ADS1299)" if is_coral() else "SİMÜLASYON (GDF)"
    trials = CAL_TRIALS_PER_CLASS * len(CLASS_NAMES)
    duration = trials * (CAL_FIXATION_S + CAL_IMAGERY_S + CAL_REST_S)

    print("=" * 60)
    print("  WHEELCHAIR BCI — OFFLİNE VERİ TOPLAMA ARACI")
    print(f"  Kaynak:   {hardware}")
    print(f"  Denemeler: {trials} ({CAL_TRIALS_PER_CLASS} × {len(CLASS_NAMES)} sınıf)")
    print(f"  Süre:     ~{duration / 60:.0f} dakika")
    print(f"  Çıktı:    {CAL_DATA_DIR}/personal_*.npz")
    print("=" * 60)

    ui.run(
        host="0.0.0.0",
        port=8081,
        title="BCI Veri Toplama",
        reload=False,
        dark=True,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
