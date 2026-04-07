"""
Wheelchair BCI — EEGNet Fine-Tuning (Kalibrasyon)
Bu modül, laboratuvarda eğitilmiş baz modeli (Base Model) alır ve
kullanıcının o anki kalibrasyon verisiyle günceller.

Sadece EEGNet'in "Separable Convolution" (Kişisel özellikler)
katmanını eğitir (Transfer Learning). Bu işlem çok hızlıdır (<1 dk).
"""

import os
from pathlib import Path
from datetime import datetime

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader
from sklearn.model_selection import StratifiedShuffleSplit

from wheelchair_bci.config import MODELS_DIR
from wheelchair_bci.decoder_training import EEGNet


def finetune_train(data_array: np.ndarray, labels_array: np.ndarray,
                   epochs: int = 20, batch_size: int = 16, lr: float = 1e-4) -> dict:
    """
    Sisteme canlı gelen (kalibrasyon sırasında kaydedilen) veriyle EEGNet'i inceler.
    Eğitilen yeni modeli _calibrated tag'iyle kaydeder.

    Parametreler:
        data_array:   (N, 1, 8, 250) numpy dizisi - µV cinsinden
        labels_array: (N,) numpy dizisi - int sınıf etiketleri
        epochs:       Maksimum iterasyon sayısı (kısa tutulur)
        batch_size:   Mini batch boyutu
        lr:           Öğrenme oranı (düşük tutulmalı - catastrophic forgetting'i önler)

    Döndürür:
        dict: {"base_accuracy": % float, "accuracy": % float}
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n[FINE-TUNE] Cihaz: {device} | Veri: {len(data_array)} örnek")

    # ── 1. En güncel modeli bul ──
    # Önce base modeli alıyoruz
    base_models = sorted(MODELS_DIR.glob("EEGNet_base_*.pt"), reverse=True)
    if not base_models:
        raise FileNotFoundError("Eğitilmiş base model (EEGNet_base_*.pt) bulunamadı!")
    
    model_path = base_models[0]
    print(f"[FINE-TUNE] Temel Model Yükleniyor: {model_path.name}")

    # ── 2. Modeli yükle ve katmanları dondur ──
    model = EEGNet()
    model.load_state_dict(torch.load(model_path, weights_only=True, map_location=device))
    model.to(device)

    # Transfer Learning: Block 1 ve Block 2'yi DONDUR (eğitilmesin)
    # Sadece Block 3 (sep_depthwise / sep_pointwise) ve Classifier güncellensin.
    for param in model.conv1.parameters():
        param.requires_grad = False
    for param in model.depthwise.parameters():
        param.requires_grad = False
    for param in model.bn1.parameters():
        param.requires_grad = False
    for param in model.bn2.parameters():
        param.requires_grad = False

    # Eğitilecek parametre sayıları:
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[FINE-TUNE] Eğitilecek Parametre Sayısı: {trainable:,}")

    # ── 3. Veri Ön Hazırlık ──
    if len(np.unique(labels_array)) < 2:
        print("[FINE-TUNE] Uyarı: En az 2 sınıf kalibrasyon verisi yok, atlanıyor.")
        return {"base_accuracy": 0.0, "accuracy": 0.0}

    try:
        sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
        tr_idx, vl_idx = next(sss.split(data_array, labels_array))
        
        X_tr = torch.from_numpy(data_array[tr_idx]).float()
        y_tr = torch.from_numpy(labels_array[tr_idx]).long()
        X_vl = torch.from_numpy(data_array[vl_idx]).float()
        y_vl = torch.from_numpy(labels_array[vl_idx]).long()
    except ValueError:
        # Eğer veri çok azsa (hata alınırsa) manuel böl
        split = int(len(data_array) * 0.8)
        X_tr = torch.from_numpy(data_array[:split]).float()
        y_tr = torch.from_numpy(labels_array[:split]).long()
        X_vl = torch.from_numpy(data_array[split:]).float()
        y_vl = torch.from_numpy(labels_array[split:]).long()
        
    train_loader = DataLoader(TensorDataset(X_tr, y_tr), batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(TensorDataset(X_vl, y_vl), batch_size=batch_size)

    # ── 4. Baseline Performansı Ölç ──
    model.eval()
    base_correct = 0
    with torch.no_grad():
        for xb, yb in val_loader:
            xb, yb = xb.to(device), yb.to(device)
            preds = model(xb).argmax(1)
            base_correct += (preds == yb).sum().item()
    
    base_acc = base_correct / max(len(y_vl), 1)
    print(f"[FINE-TUNE] Eğitimsiz (Base) Doğruluk: {base_acc*100:.1f}%")

    # ── 5. Fine-Tune Eğitimi ──
    optimizer = torch.optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=lr)
    criterion = nn.CrossEntropyLoss()

    best_acc = base_acc
    best_state = None

    for epoch in range(1, epochs + 1):
        model.train()
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            optimizer.step()
            model.apply_max_norm()

        model.eval()
        val_correct = 0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                preds = model(xb).argmax(1)
                val_correct += (preds == yb).sum().item()
        
        val_acc = val_correct / max(len(y_vl), 1)
        if val_acc > best_acc:
            best_acc = val_acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            
    print(f"[FINE-TUNE] Eğitim Bitti! Yeni Doğruluk: {best_acc*100:.1f}%")

    # ── 6. Modeli Kaydet ──
    if best_state:
        # Performans artmışsa kaydet
        model.load_state_dict(best_state)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"EEGNet_calibrated_{timestamp}.pt"
        save_path = MODELS_DIR / filename
        
        torch.save(model.state_dict(), str(save_path))
        print(f"[FINE-TUNE] Kişiselleştirilmiş model kaydedildi: {filename}")
    else:
        print("[FINE-TUNE] Doğruluk artmadı, model güncellenmedi.")

    return {
        "base_accuracy": float(np.round(base_acc * 100, 1)),
        "accuracy": float(np.round(best_acc * 100, 1))
    }
