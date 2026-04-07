"""
Wheelchair BCI — Inference Motoru
EEGNet modelini çalıştırarak EEG penceresinden komut tahmini üretir.

Üç motor desteklenir (öncelik sırasıyla):
  1. TFLite Edge TPU  — Coral üzerinde ~2-5ms inference
  2. TFLite CPU        — Edge TPU yoksa CPU üzerinde float32
  3. PyTorch            — Laptop/PC test ortamı için fallback
"""

import sys
from pathlib import Path

import numpy as np

from wheelchair_bci.config import CLASS_NAMES, MODELS_DIR, PROJECT_ROOT


# ══════════════════════════════════════════════════
# TFLITE INFERENCE MOTORU
# ══════════════════════════════════════════════════

class TFLiteEngine:
    """
    TFLite ile EEGNet inference — Edge TPU veya CPU.

    Edge TPU modeli (_edgetpu.tflite) varsa donanım hızlandırıcıda,
    yoksa normal TFLite CPU'da çalışır.
    Int8 kuantize modeller için otomatik dequantize yapar.
    """

    def __init__(self, model_path: Path):
        """
        TFLite interpreter'ı yükler ve tensör bilgilerini alır.

        Parametreler:
            model_path: .tflite model dosyasının yolu
        """
        try:
            # Coral/Mendel Linux'ta tflite_runtime yüklüdür
            from tflite_runtime.interpreter import Interpreter
            from tflite_runtime.interpreter import load_delegate

            if "_edgetpu" in str(model_path):
                # Edge TPU delegesi ile donanım hızlandırma
                self.interpreter = Interpreter(
                    str(model_path),
                    experimental_delegates=[load_delegate("libedgetpu.so.1")],
                )
                print(f"[MODEL] Edge TPU: {model_path.name}")
            else:
                self.interpreter = Interpreter(str(model_path))
                print(f"[MODEL] TFLite CPU: {model_path.name}")

        except ImportError:
            # Fallback: tam TensorFlow paketi
            import tensorflow as tf
            self.interpreter = tf.lite.Interpreter(str(model_path))
            print(f"[MODEL] TFLite (tf): {model_path.name}")

        # Tensör hafızasını ayır ve giriş/çıkış detaylarını al
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        
        # Dinamik eşik yükleme
        from wheelchair_bci.config import CONFIDENCE_THRESHOLD
        self.dynamic_threshold = CONFIDENCE_THRESHOLD
        json_path = Path(str(model_path).replace("_edgetpu.tflite", "").replace("_int8.tflite", "").replace(".tflite", ""))
        json_path = json_path.with_suffix(".json")
        if json_path.exists():
            try:
                import json
                with open(json_path, "r") as f:
                    stats = json.load(f)
                    self.dynamic_threshold = stats.get("dynamic_threshold", CONFIDENCE_THRESHOLD)
                    print(f"[INFERENCE] Dinamik eşik yüklendi (TFLite): {self.dynamic_threshold:.3f}")
            except Exception:
                pass

        inp = self.input_details[0]
        out = self.output_details[0]
        print(f"[MODEL] Input:  {inp['shape']}  dtype={inp['dtype']}")
        print(f"[MODEL] Output: {out['shape']}  dtype={out['dtype']}")

        # ── Kuantizasyon parametreleri (int8 modeller için) ──
        # Int8 modelde giriş/çıkış scale ve zero_point ile dönüştürülür
        quant_in = inp.get("quantization_parameters", {})
        quant_out = out.get("quantization_parameters", {})

        self.input_scale = quant_in.get("scales", [1.0])[0]
        self.input_zero = quant_in.get("zero_points", [0])[0]
        self.output_scale = quant_out.get("scales", [1.0])[0]
        self.output_zero = quant_out.get("zero_points", [0])[0]
        self.is_int8 = (inp["dtype"] == np.int8)

    def predict(self, window: np.ndarray) -> tuple[str, float, np.ndarray]:
        """
        1 saniyelik EEG penceresinden komut tahmini üretir.

        Parametreler:
            window: np.ndarray, shape (250, 8) — zaman × kanal, volt cinsinden

        Döndürür:
            command:    str        — "F", "L", "R" veya "S"
            confidence: float      — en yüksek olasılık (0-1 arası)
            probs:      np.ndarray — 4 sınıfın olasılık dağılımı
        """
        # Yeniden şekillendirme: (250,8) → (1,1,8,250) ve V → µV dönüşümü
        x = window.T[np.newaxis, np.newaxis, :, :].astype(np.float32) * 1e6

        if self.is_int8:
            # Float32 → Int8 kuantizasyon (modelin beklediği format)
            x = (x / self.input_scale + self.input_zero).clip(-128, 127).astype(np.int8)

        # Modeli çalıştır
        self.interpreter.set_tensor(self.input_details[0]["index"], x)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_details[0]["index"])

        if self.is_int8:
            # Int8 → Float32 dequantizasyon
            output = (output.astype(np.float32) - self.output_zero) * self.output_scale

        # Softmax: ham logitlerden olasılık dağılımına
        logits = output[0]
        exp_logits = np.exp(logits - np.max(logits))   # sayısal kararlılık için max çıkar
        probs = exp_logits / exp_logits.sum()

        pred_idx = int(np.argmax(probs))
        command = CLASS_NAMES[pred_idx]
        confidence = float(probs[pred_idx])

        return command, confidence, probs


# ══════════════════════════════════════════════════
# PYTORCH INFERENCE MOTORU (FALLBACK)
# ══════════════════════════════════════════════════

class PyTorchEngine:
    """
    PyTorch ile EEGNet inference — laptop/PC test ortamı için.

    Coral'da TFLite kullanılır; bu sınıf sadece geliştirme ve
    debug amaçlı çalışır. GPU varsa CUDA kullanır.
    """

    def __init__(self, model_path: Path):
        """
        PyTorch .pt model dosyasını yükler.

        Parametreler:
            model_path: .pt model dosyasının yolu
        """
        import torch
        import torch.nn.functional as F
        self.torch = torch
        self.F = F

        # EEGNet sınıfını eğitim scriptinden import et
        from wheelchair_bci.decoder_training import EEGNet

        # GPU varsa kullan, yoksa CPU
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Model ağırlıklarını yükle
        self.model = EEGNet()
        self.model.load_state_dict(
            torch.load(str(model_path), weights_only=True, map_location=self.device)
        )
        self.model.to(self.device)
        self.model.eval()

        from wheelchair_bci.config import CONFIDENCE_THRESHOLD
        self.dynamic_threshold = CONFIDENCE_THRESHOLD
        json_path = model_path.with_suffix(".json")
        if json_path.exists():
            try:
                import json
                with open(json_path, "r") as f:
                    stats = json.load(f)
                    self.dynamic_threshold = stats.get("dynamic_threshold", CONFIDENCE_THRESHOLD)
                    print(f"[INFERENCE] Dinamik eşik yüklendi (PyTorch): {self.dynamic_threshold:.3f}")
            except Exception:
                pass   # Dropout ve BatchNorm'u eval moduna al

        total_params = sum(p.numel() for p in self.model.parameters())
        print(f"[MODEL] PyTorch: {model_path.name} ({total_params:,} params) on {self.device}")

    def predict(self, window: np.ndarray) -> tuple[str, float, np.ndarray]:
        """
        1 saniyelik EEG penceresinden komut tahmini üretir.
        (Arayüz TFLiteEngine ile aynı)
        """
        # (250,8) → (1,1,8,250), V → µV
        x = window.T[np.newaxis, np.newaxis, :, :].astype(np.float32) * 1e6
        x_tensor = self.torch.from_numpy(x).to(self.device)

        with self.torch.no_grad():
            logits = self.model(x_tensor)
            probs = self.F.softmax(logits, dim=1).cpu().numpy()[0]

        pred_idx = int(np.argmax(probs))
        command = CLASS_NAMES[pred_idx]
        confidence = float(probs[pred_idx])

        return command, confidence, probs


# ══════════════════════════════════════════════════
# MODEL KEŞFİ VE FABRİKA FONKSİYONU
# ══════════════════════════════════════════════════

def find_model():
    """
    models/ klasöründe en uygun modeli öncelik sırasıyla bulur:
      1. Edge TPU derlenmiş  (*_edgetpu.tflite)
      2. Int8 TFLite         (*_int8.tflite)
      3. Float32 TFLite      (*.tflite)
      4. PyTorch             (*.pt)

    Döndürür:
        (model_path, model_type) veya (None, None)
    """
    if not MODELS_DIR.exists():
        return None, None

    # Öncelik sırası: edgetpu > int8 > float32 tflite > pytorch
    search_order = [
        ("*_edgetpu.tflite", "edgetpu"),
        ("*_int8.tflite",    "tflite"),
        ("*.tflite",         "tflite"),
        ("*.pt",             "pytorch"),
    ]

    for pattern, model_type in search_order:
        matches = sorted(MODELS_DIR.glob(pattern), reverse=True)
        if matches:
            return matches[0], model_type

    return None, None


def load_engine(model_path: Path = None, model_type: str = None):
    """
    Uygun inference motorunu yükler ve döndürür.

    Parametre verilmezse otomatik keşif yapar (find_model).

    Döndürür:
        TFLiteEngine veya PyTorchEngine örneği

    Hata:
        FileNotFoundError — model bulunamazsa
    """
    if model_path is None:
        model_path, model_type = find_model()

    if model_path is None:
        raise FileNotFoundError(
            "models/ klasöründe model bulunamadı.\n"
            "Önce eğitim scriptini çalıştırın."
        )

    print(f"[INIT] Model: {model_path.name} (type={model_type})")

    if model_type in ("edgetpu", "tflite"):
        return TFLiteEngine(model_path)
    else:
        return PyTorchEngine(model_path)
