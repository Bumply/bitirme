"""
Wheelchair BCI — Komut Yumuşatıcı (Command Smoother)
Anlık tahmin gürültüsünü (jitter) önlemek için majority vote uygular.
Düşük güvenli tahminleri filtreler, son N tahminin çoğunluğunu alır.
"""

import collections

from wheelchair_bci.config import CONFIDENCE_THRESHOLD, VOTE_WINDOW


class CommandSmoother:
    """
    Beyin-bilgisayar arayüzünde tahminler doğası gereği gürültülüdür.
    Art arda F-L-F-F geldiğinde sandalyeyi her seferinde farklı yöne
    göndermek tehlikelidir. Bu sınıf bunu önler:

    1. Güven eşiği:  Düşük güvenli tahminler → yok sayılır
    2. Majority vote: Son N tahminin çoğunluğu → nihai komut olur
    3. Berabere:      Oy eşitliğinde → son onaylanan komut korunur
    """

    def __init__(self, window_size: int = VOTE_WINDOW, threshold: float = None):
        """
        Parametreler:
            window_size: Kaç tahminin çoğunluğu alınacak (varsayılan 3)
            threshold: Dinamik güven eşiği (None verilirse config'dekini kullanır)
        """
        self.window_size = window_size
        self.threshold = threshold if threshold is not None else CONFIDENCE_THRESHOLD

        # Son N tahmini tutan sabit boyutlu kuyruk (FIFO)
        # maxlen=3 ise 4. eleman eklenince en eski otomatik düşer
        self.history = collections.deque(maxlen=window_size)

        # Son onaylanan (doğrulanmış) komut
        self.last_command = "S"

    def update(self, command: str, confidence: float) -> tuple[str, str]:
        """
        Yeni bir tahmin geldiğinde çağrılır.

        Parametreler:
            command:    str   — ham tahmin ("F", "L", "R", "S")
            confidence: float — modelin güven skoru (0-1)

        Döndürür:
            (smooth_command, reason) çifti:
            - smooth_command: filtrelenmiş nihai komut
            - reason: karar sebebi ("VOTE", "LOW_CONF", "FILLING", "TIE")
        """

        # ── Adım 1: Güven kontrolü ──
        # Güven eşiğinin altındaysa → bu tahmine güvenme, eskisini koru
        if confidence < self.threshold:
            return self.last_command, "LOW_CONF"

        # ── Adım 2: Geçmişe ekle ──
        self.history.append(command)

        # ── Adım 3: Pencere doldu mu? ──
        # İlk birkaç tahmin boyunca pencere dolana kadar bekle
        if len(self.history) < self.window_size:
            return self.last_command, "FILLING"

        # ── Adım 4: Majority vote (çoğunluk oylaması) ──
        # Penceredeki her komutun kaç kez geçtiğini say
        counts = {}
        for cmd in self.history:
            counts[cmd] = counts.get(cmd, 0) + 1

        max_count = max(counts.values())
        winners = [cmd for cmd, cnt in counts.items() if cnt == max_count]

        # Tek bir kazanan varsa → komutu güncelle
        if len(winners) == 1:
            self.last_command = winners[0]
            return self.last_command, "VOTE"

        # Berabere → mevcut komutu koru (güvenli tarafta kal)
        return self.last_command, "TIE"

    def reset(self):
        """Geçmişi temizler ve STOP'a döner."""
        self.history.clear()
        self.last_command = "S"
