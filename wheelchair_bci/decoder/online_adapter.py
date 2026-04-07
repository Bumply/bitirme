"""
Wheelchair BCI — Online Adaptasyon (Pseudo-Label Fine-Tune)
Kullanım sırasında beyin sinyalleri değişir (yorgunluk, elektrot kayması).
Yüksek güvenli tahminleri pseudo-label olarak biriktirip modeli
canlı olarak hafifçe günceller — kalibrasyon bilgisi korunur.
Sadece PyTorch motoruyla çalışır (TFLite modeli frozen'dır).
"""

import numpy as np

from wheelchair_bci.config import (
    CLASS_NAMES,
    ADAPT_ENABLED,
    ADAPT_CONFIDENCE,
    ADAPT_BUFFER_SIZE,
    ADAPT_MICRO_EPOCHS,
    ADAPT_LR,
)


class OnlineAdapter:
    """
    Oturum içi model adaptasyonu.

    Neden gerekli?
    - EEG sinyalleri sabit değildir: yorgunluk, dikkat değişimi,
      elektrot jeli kuruması, ter vs. model performansını düşürür.
    - Statik bir model zamanla doğruluğunu kaybeder.

    Nasıl çalışır?
    1. Her inference sonrasında — güven %80'in üzerindeyse —
       o pencereyi "pseudo-label" olarak kaydeder
    2. 50 pseudo-label birikince micro fine-tune çalıştırır
    3. Yalnızca Block3 (separable conv) + classifier güncellenir
       → Block1+2'deki evrensel özellikler dokunulmaz
    4. Çok düşük LR (5e-5) ile kalibrasyon bilgisi korunur

    Güvenlik:
    - Sadece PyTorch motoru desteklenir (TFLite frozen'dır)
    - Adaptasyon başarısız olursa orijinal model diskte duruyor → restart ile geri dön
    """

    def __init__(self, engine):
        """
        Parametreler:
            engine: PyTorchEngine veya TFLiteEngine — inference motoru
        """
        # PyTorch motoru mu kontrol et (hasattr 'model' → PyTorch)
        self.enabled = ADAPT_ENABLED and hasattr(engine, "model")
        self.engine = engine

        if not self.enabled:
            reason = "PyTorch motoru gerekli" if ADAPT_ENABLED else "config'de kapalı"
            print(f"[ADAPT] Devre dışı — {reason}")
            return

        # Sınıf isimlerini sayısal indekse çeviren sözlük
        # {"F": 0, "L": 1, "R": 2, "S": 3}
        self.label_to_idx = {c: i for i, c in enumerate(CLASS_NAMES)}

        # Pseudo-label biriktirme tamponları
        self.windows = []       # Ham EEG pencereleri — (250, 8) dizileri
        self.labels = []        # Sayısal sınıf indeksleri — [0, 1, 2, ...]

        # İstatistikler
        self.total_adapted = 0  # Toplam adapt edilen örnek sayısı
        self.adapt_count = 0    # Kaç kez micro fine-tune yapıldı

        # Optimizer'ı hazırla (sadece eğitilebilir parametreler için)
        self._setup_optimizer()

        print(
            f"[ADAPT] Online adaptasyon aktif: "
            f"güven>{ADAPT_CONFIDENCE*100:.0f}%, "
            f"tampon={ADAPT_BUFFER_SIZE}, "
            f"lr={ADAPT_LR}"
        )

    def _setup_optimizer(self):
        """
        Block 1+2'yi dondur, Block 3 + classifier'ı eğitilebilir yap.

        EEGNet mimarisi:
          Block 1: Temporal conv + BatchNorm   → DONDUR (evrensel zaman özellikleri)
          Block 2: Depthwise conv + BatchNorm  → DONDUR (evrensel uzamsal özellikler)
          Block 3: Separable conv + BatchNorm  → EĞİT  (kişiye özel özellikler)
          Classifier: Linear katman            → EĞİT  (karar sınırları)
        """
        import torch
        import torch.nn as nn
        self.torch = torch
        self.nn = nn

        model = self.engine.model

        # Önce tümünü dondur
        for param in model.parameters():
            param.requires_grad = False

        # Sadece Block 3 + classifier'ı aç
        trainable_keywords = ["sep_depthwise", "sep_pointwise", "bn3", "classifier"]
        for name, param in model.named_parameters():
            if any(kw in name for kw in trainable_keywords):
                param.requires_grad = True

        # Eğitilebilir parametreler için optimizer
        trainable_params = [p for p in model.parameters() if p.requires_grad]
        self.optimizer = torch.optim.Adam(trainable_params, lr=ADAPT_LR)
        self.criterion = nn.CrossEntropyLoss()

        n_trainable = sum(p.numel() for p in trainable_params)
        print(f"[ADAPT] Eğitilebilir parametre: {n_trainable:,}")

    def accumulate(self, window: np.ndarray, command: str, confidence: float):
        """
        Her inference sonrasında çağrılır. Güven yeterince yüksekse
        pencereyi pseudo-label olarak kaydeder.

        Parametreler:
            window:     np.ndarray, shape (250, 8) — filtrelenmiş EEG
            command:    str   — modelin tahmini ("F", "L", "R", "S")
            confidence: float — güven skoru
        """
        if not self.enabled:
            return

        # Güven eşiğinin altındaysa → pseudo-label olarak güvenilmez, atla
        if confidence < ADAPT_CONFIDENCE:
            return

        # Bilinmeyen komut kontrolü
        if command not in self.label_to_idx:
            return

        # Tampona ekle
        self.windows.append(window.copy())
        self.labels.append(self.label_to_idx[command])

        # Tampon doldu mu? → Micro fine-tune yap
        if len(self.windows) >= ADAPT_BUFFER_SIZE:
            self._micro_finetune()

    def _micro_finetune(self):
        """
        Birikmiş pseudo-label veriyle hızlı bir fine-tune çalıştırır.
        5 epoch × ~50 örnek → birkaç milisaniye sürer.
        """
        torch = self.torch
        model = self.engine.model
        device = self.engine.device

        n = len(self.windows)
        self.adapt_count += 1

        # ── Veriyi hazırla ──
        # (n, 250, 8) → (n, 1, 8, 250), V → µV
        X = np.array(self.windows)
        X = X.transpose(0, 2, 1)[:, np.newaxis, :, :].astype(np.float32) * 1e6
        y = np.array(self.labels)

        X_t = torch.from_numpy(X).to(device)
        y_t = torch.from_numpy(y).long().to(device)

        # Sınıf dağılımını logla
        dist = {CLASS_NAMES[i]: int(np.sum(y == i)) for i in range(len(CLASS_NAMES))}

        # ── Eğitim modu ──
        model.train()

        # Dondurulmuş BatchNorm'ları eval'de tut → istatistikleri bozma
        for m in model.modules():
            if isinstance(m, self.nn.BatchNorm2d) and not m.weight.requires_grad:
                m.eval()

        # ── Micro fine-tune döngüsü ──
        losses = []
        for epoch in range(ADAPT_MICRO_EPOCHS):
            self.optimizer.zero_grad()
            logits = model(X_t)
            loss = self.criterion(logits, y_t)
            loss.backward()
            self.optimizer.step()

            # Max-norm constraint (EEGNet regularizasyon)
            if hasattr(model, "apply_max_norm"):
                model.apply_max_norm()

            losses.append(loss.item())

        # ── Eval moduna geri dön ──
        model.eval()

        self.total_adapted += n
        avg_loss = sum(losses) / len(losses)

        print(
            f"[ADAPT] Micro fine-tune #{self.adapt_count}: "
            f"{n} örnek, loss={avg_loss:.4f}, "
            f"dağılım={dist}, toplam={self.total_adapted}"
        )

        # Tamponu temizle
        self.windows.clear()
        self.labels.clear()

    def get_stats(self) -> dict:
        """Adaptasyon istatistiklerini döndürür (loglama için)."""
        return {
            "enabled": self.enabled,
            "buffer_size": len(self.windows) if self.enabled else 0,
            "adapt_count": self.adapt_count if self.enabled else 0,
            "total_adapted": self.total_adapted if self.enabled else 0,
        }
