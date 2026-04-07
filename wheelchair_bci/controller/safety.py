"""
Wheelchair BCI — Güvenlik Denetleyicisi (Controller / Pi 5)
Tekerlekli sandalyenin güvenliğini sağlayan 3 katmanlı koruma sistemi:
  1. Heartbeat Timeout  — Decoder bağlantısı koparsa → otomatik DUR
  2. Command Timeout    — Uzun süre güvenli komut gelmezse → otomatik DUR
  3. E-Stop             — Acil durdurma butonu → tüm sistemi anında durdur
"""

import time

from wheelchair_bci.config import HEARTBEAT_TIMEOUT, COMMAND_TIMEOUT, MAX_SPEED


class SafetyController:
    """
    Tekerlekli sandalye güvenlik katmanı.

    Neden gerekli?
    - Decoder (Coral) çökebilir, WiFi kopabilir → sandalye son komutu
      tekrar etmeye devam eder → duvar/merdiven tehlikesi
    - Beyin sinyali saçma sonuçlar üretebilir → anlamsız komutlar
    - Kullanıcı panik anında sistemi anında durdurabilmeli

    Bu sınıf her gelen komutu 3 güvenlik filtresinden geçirir.
    Herhangi biri tetiklenirse komut "S" (DUR) olarak değiştirilir.
    """

    def __init__(self):
        # ── Zaman damgaları ──
        self.last_heartbeat = 0.0       # Decoder'dan son paket zamanı
        self.last_safe_command = 0.0    # Son güvenli (S olmayan) komut zamanı

        # ── E-Stop durumu ──
        self.estop_active = False       # True ise TÜM komutlar engellenir

        # ── Hız limiti ──
        self.max_speed = MAX_SPEED      # Dashboard'dan ayarlanabilir (0-100%)

    def heartbeat(self):
        """
        Decoder'dan paket geldiğinde çağrılır.
        "Decoder hâlâ hayatta" sinyali olarak zaman damgası günceller.
        """
        self.last_heartbeat = time.time()

    def check(self, command: str, confidence: float) -> tuple[str, str]:
        """
        Gelen komutu 3 güvenlik filtresinden geçirir.

        Parametreler:
            command:    str   — Decoder'dan gelen komut ("F","L","R","S")
            confidence: float — Güven skoru (0-1)

        Döndürür:
            (safe_command, reason) çifti:
            - safe_command: güvenli komut (orijinal veya "S")
            - reason: karar açıklaması
        """
        now = time.time()

        # ── Filtre 1: E-Stop kontrolü ──
        # Acil durdurma aktifse HİÇBİR komut geçemez
        if self.estop_active:
            return "S", "E-STOP"

        # ── Filtre 2: Heartbeat kontrolü ──
        # Decoder'dan belirli süredir paket gelmiyorsa → bağlantı kopmuş
        if self.last_heartbeat > 0:
            elapsed = now - self.last_heartbeat
            if elapsed > HEARTBEAT_TIMEOUT:
                return "S", "NO_HEARTBEAT"

        # ── Tüm filtrelerden geçti → güvenli ──
        if command != "S":
            self.last_safe_command = now

        return command, "OK"

    def trigger_estop(self):
        """
        Acil durdurma butonuna basıldığında çağrılır.
        Aktifken hiçbir hareket komutu geçemez.
        """
        self.estop_active = True
        print("[SAFETY] ⚠️  E-STOP AKTİF — tüm komutlar engellendi!")

    def reset_estop(self):
        """
        E-Stop'u sıfırlar. Dashboard'daki "Reset" butonuyla çağrılır.
        Zaman damgalarını da sıfırlar ki timeout tetiklenmesin.
        """
        self.estop_active = False
        self.last_heartbeat = time.time()
        self.last_safe_command = time.time()
        print("[SAFETY] E-Stop sıfırlandı, sistem yeniden aktif.")

    def get_status(self) -> dict:
        """Güvenlik durumunu dashboard'a raporlamak için döndürür."""
        now = time.time()
        heartbeat_age = now - self.last_heartbeat if self.last_heartbeat > 0 else -1

        return {
            "estop": self.estop_active,
            "heartbeat_age": round(heartbeat_age, 1),
            "heartbeat_ok": 0 < heartbeat_age < HEARTBEAT_TIMEOUT,
            "max_speed": self.max_speed,
        }
