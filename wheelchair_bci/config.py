"""
Wheelchair BCI — Merkezi Konfigürasyon
Tüm düğümler (Node1, Node2) bu dosyayı import eder.
"""

from pathlib import Path

# ══════════════════════════════════════════════════
# 1. EEG DONANIM PARAMETRELERİ
# ══════════════════════════════════════════════════

FS = 250                        # Örnekleme frekansı (Hz). ADS1299, saniyede 250 örnek okur.
N_CH = 8                        # Toplam kanal sayısı (8 kanallı EEG şapkası)
CHANNELS = [                    # Her kanalın fiziksel elektrot konumu (10-20 sistemi)
    "FC3", "FC4",               #   Fronto-santral sol/sağ — motor planlama bölgeleri
    "C3", "Cz", "C4",          #   Santral sol/orta/sağ — birincil motor korteks
    "CP3", "CP4",               #   Centro-parietal sol/sağ — duyusal-motor arayüzü
    "FCz",                      #   Fronto-santral orta — ek kanal
]

# ══════════════════════════════════════════════════
# 2. DSP — DİJİTAL SİNYAL İŞLEME
# ══════════════════════════════════════════════════

NOTCH_FREQ = 50                 # Notch filtre frekansı (Hz). Türkiye şebeke gürültüsü 50Hz.
BANDPASS_LOW = 8                # Bandpass alt kesim (Hz). 8Hz altı: göz kırpma ve drift.
BANDPASS_HIGH = 30              # Bandpass üst kesim (Hz). 8-30Hz: mu + beta ritimleri.

# ══════════════════════════════════════════════════
# 3. SINIFLANDIRMA VE KOMUT EŞLEME
# ══════════════════════════════════════════════════

CLASS_NAMES = ["F", "L", "R", "S"]   # F=Forward(ayak), L=Left(sağ el),
                                      # R=Right(sol el), S=Stop(dil)

CONFIDENCE_THRESHOLD = 0.40           # Minimum güven eşiği. Bunun altındaki tahminler
                                      # "emin değilim" sayılır ve komut değiştirilmez.

VOTE_WINDOW = 3                       # Majority vote pencere boyutu. Son 3 tahminin
                                      # çoğunluğu alınır → jitter/titreşim önlenir.

BUFFER_SECONDS = 1.0                  # Inference pencere uzunluğu (saniye).
                                      # Her sınıflandırma 1 saniyelik EEG verisine bakar.
BUFFER_SIZE = int(FS * BUFFER_SECONDS)  # = 250 örnek (1 saniye x 250 SPS)

DSP_INTERVAL = 0.5                    # İki inference arası bekleme (saniye).
                                      # Her 500ms'de bir yeni tahmin yapılır.

# ── Artifact Rejection (Göz kırpma / kas hareketi filtresi) ──
ARTIFACT_PEAK_UV = 100.0              # µV. Bu eşiği aşan bir kanal → pencere kirlenmiş.
                                      # Göz kırpma ~150-300µV, kas hareketi ~50-200µV.
ARTIFACT_VARIANCE_UV2 = 5000.0        # µV². Ortalama varyans bu değeri aşarsa → yüksek gürültü.
                                      # Normal mu/beta: 10-100 µV², artifact: 1000+ µV².

# ══════════════════════════════════════════════════
# 4. AĞ AYARLARI (WIFI UDP)
# ══════════════════════════════════════════════════

# Decoder (Coral), kendi WiFi Access Point'ini yayınlar.
# Controller (Pi 5), bu AP'ye istemci olarak bağlanır.
DECODER_IP = "127.0.0.1"          # Coral'ın IP adresi (localhost test için)
# Controller Düğümü (Raspberry Pi 5) Hedef IP'si
# Not: Eğer sistemi masaüstü bilgisayarda (localhost) test ediyorsanız "127.0.0.1" yapın.
# Eğer Coral, Pi5'in Hotspot ağına bağlıysa "192.168.4.1" gibi bir değer yapın.
CONTROLLER_IP = "127.0.0.1"

UDP_CMD_PORT = 5000             # Komut portu: Node1 → Node2 yönünde tahmin paketleri
UDP_CAL_PORT = 5001             # Kalibrasyon portu: Node2 → Node1 yönünde cue kontrol paketleri

# ══════════════════════════════════════════════════
# 5. ARDUINO SERİAL & GÜVENLİK
# ══════════════════════════════════════════════════

SERIAL_PORT = "/dev/ttyACM0"    # Arduino'nun Linux/Pi'deki seri port yolu
SERIAL_BAUD = 115200            # Seri haberleşme hızı (baud rate)
SERIAL_ENABLED = False          # True yapılınca Arduino'ya gerçekten komut gider.
                                # False iken sadece terminale yazdırır (simülasyon).

HEARTBEAT_TIMEOUT = 3.0         # Saniye. Node1'den 3s boyunca paket gelmezse → otomatik DUR.
COMMAND_TIMEOUT = 5.0           # Saniye. 5s boyunca güvenli komut gelmezse → otomatik DUR.
MAX_SPEED = 100                 # Yüzde (0-100). Dashboard'dan ayarlanabilir hız limiti.

# ══════════════════════════════════════════════════
# 6. KALİBRASYON PROTOKOLÜ
# ══════════════════════════════════════════════════

CAL_FIXATION_S = 2.0            # Çarpı işareti süresi (saniye). Dikkat toplama fazı.
CAL_IMAGERY_S = 4.0             # Motor imagery süresi (saniye). Veri kaydedilen faz.
CAL_REST_S = 2.0                # Dinlenme süresi (saniye). Denemeler arası mola.
CAL_TRIALS_PER_CLASS = 25       # Her sınıf için deneme sayısı. 25 x 4 = 100 deneme.

# ══════════════════════════════════════════════════
# 7. ONLINE ADAPTASYON
# ══════════════════════════════════════════════════

ADAPT_ENABLED = True            # Online adaptasyonu aç/kapat.
ADAPT_CONFIDENCE = 0.80         # Yalnızca %80+ güvenli tahminler pseudo-label olur.
ADAPT_BUFFER_SIZE = 50          # Bu kadar pseudo-label birikince micro fine-tune başlar.
ADAPT_MICRO_EPOCHS = 5          # Her micro fine-tune'da kaç epoch eğitim yapılacak.
ADAPT_LR = 0.00005              # Çok düşük öğrenme oranı — kalibrasyon bilgisini unutmasın.

# ══════════════════════════════════════════════════
# 8. DOSYA YOLLARI
# ══════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # Wheelchair/ klasörü
MODELS_DIR = PROJECT_ROOT / "models"                   # Eğitilmiş modeller
CAL_DATA_DIR = PROJECT_ROOT / "calibration_data"       # Kalibrasyon verileri
LOG_DIR = PROJECT_ROOT / "logs"                        # Çalışma logları

# ══════════════════════════════════════════════════
# 9. ADS1299 SPI (SADECE CORAL)
# ══════════════════════════════════════════════════

SPI_BUS = 0                     # SPI veri yolu numarası
SPI_DEVICE = 0                  # SPI cihaz numarası (chip select)
SPI_SPEED = 2_000_000           # SPI saat hızı: 2 MHz

# ══════════════════════════════════════════════════
# 10. OTA MODEL GÜNCELLEMESİ
# ══════════════════════════════════════════════════

OTA_PORT = 5002                 # TCP portu: Pi5 → Coral model dosyası gönderir
OTA_MAX_SIZE = 10_000_000       # Maksimum model boyutu (10 MB). Güvenlik limiti.

# ══════════════════════════════════════════════════
# 11. LEAD-OFF (ELEKTROT KOPMA) ALGILAMA
# ══════════════════════════════════════════════════

LEAD_OFF_ENABLED = True         # Lead-off algılamayı aç/kapat
LEAD_OFF_THRESHOLD = 3          # Ardışık kaç kopma okunursa güvenli moda geçilsin

# ══════════════════════════════════════════════════
# 12. DASHBOARD
# ══════════════════════════════════════════════════

DASHBOARD_PORT = 8080           # Web arayüzü portu (http://<pi-ip>:8080)
HISTORY_SIZE = 200              # Komut logunda tutulacak son N kayıt
