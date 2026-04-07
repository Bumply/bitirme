# BCI Wheelchair — Başlangıç ve Çalıştırma Rehberi

Bu proje modüler (parçalı) bir yapıda tasarlandığı için her bir klasörü veya dosyayı tek tek çalıştırmana gerek yoktur. Sistem temelde 3 ana "Giriş Kapısı" üzerinden çalışır.

Tüm komutlar ana proje dizini olan `Wheelchair/` klasörünün içinde terminalden (veya komut satırından) çalıştırılmalıdır.

---

## 🏎 1. Akıllı Sandalyeyi ve Arayüzü Başlatmak (Raspberry Pi 5)
Tekerlekli sandalyenin üzerindeki ana beyin olan Raspberry Pi 5 açıldığında sadece bu komut çalıştırılır:

```bash
python3 -m wheelchair_bci.controller.main
```

**Ne işe yarar?**
- Kalp atışı (Heartbeat) dinlemeye başlar. Güvenlik yöneticisini (Safety Controller) devreye sokar.
- E-Stop (Acil Durdurma) mekanizmasını izler.
- Motorları hareket ettirmek için Arduino ile Seri Port (-Serial-) haberleşmesini başlatır.
- UDP üzerinden kafadaki Coral cihazından gelecek beyin komutlarını dinlemeye başlar.
- **En önemlisi:** Sistem arayüzünü (Dashboard) başlatır. Böylece telefondan veya bilgisayardan `http://<pi5-ip>:8080` adresine girerek tekerlekli sandalyeyi anlık olarak izleyebilir, kalibrasyon yapabilir ve gecikmeleri (ping) görebilirsin.

---

## 🧠 2. Beyin Okuyucuyu Başlatmak (Google Coral)
Hastanın kafasına takılan (veya hemen yanına konan) ADS1299 EEG çipine bağlı olan Google Coral cihazı açıldığında bu komut çalıştırılır:

```bash
python3 -m wheelchair_bci.decoder.main
```

**Ne işe yarar?**
- `models/` klasöründeki en güncel yapay zeka modelini (`.pt` veya `.tflite`) otomatik bulur ve belleğe yükler.
- Çipten (ADS1299) saniyede 250 kere kafatasından gelen mikro voltaj sinyallerini okur.
- Yeni eklediğimiz güvenlik filtrelerini çalıştırır:
  - *"Donanımsal elektrot koptu mu?"* (Lead-Off)
  - *"Kullanıcı göz mü kırptı / çenesini mi sıktı?"* (Artifact Rejection)
- Her şey temizse modeli çalıştırıp beynin ne düşündüğünü (Sol, Sağ, İleri, Dur) tahmin eder.
- Tahmini yumuşatıp (Command Smoother) Raspberry Pi 5'e kablosuz ağ (WiFi) üzerinden gönderir.
- Arka planda gizlice "Yeni model gelirse anında değiştir" diyerek OTA sunucusunu dinler.

---

## 🏋️ 3. Yeni Beyin Modeli Eğitmek (Güçlü Bilgisayar / Laptop)
Yapay zekanın doğruluğunu artırmak için yeni EEG verileri topladığında veya sistemi ilk kez kurduğunda çalıştırılır:

```bash
python3 -m wheelchair_bci.decoder_training --moabb --personal
```

**Ne işe yarar?**
- `--moabb` bayrağı sayesinde BCI-IV-2a (8 farklı kişinin beyin verisi) internet üzerinden otomatik indirilir.
- `--personal` bayrağı ile bu devasa yabancı veri havuzu, **senin kalibrasyon verilerinle (A01_E) harmanlanır**.
- PyTorch ile çok güçlü, genelleme yeteneği yüksek bir "EEGNet" ana modeli (`.pt`) eğitilir.
- Orijinal dosyaya dokunmadan modeli otomatik olarak Google Coral'ın çok hızlı çalıştırabileceği `.tflite` (Edge TPU için Int8 Kuantize) ve `.onnx` formatlarına çevirir (Export eder).
- Eğitilen modelin gerçek performansı dinamik bir JSON dosyasına (`_metrics.json`) kaydedilir (Dinamik Güven Eşiği için).

---

## 📡 4. "Kablo Bağlamadan" Modeli Cihaza Yüklemek (OTA)
Bilgisayarında veya Pi5'te 3. adımdaki gibi sistemi eğittin ve elinde taze, süper zeki bir `.tflite` modeli var. Bu modeli kafada çalışan Coral cihazına (onun yanına gidip kablo bağlamadan) atmak için çalıştırılır:

```bash
python3 -m wheelchair_bci.ota_push models/<yeni_egitilen_model_adi>.tflite
```

**Ne işe yarar?**
- Belirttiğin model dosyasını paketler ve WiFi üzerinden Coral'a gönderir.
- Coral arka planda (çalışması hiç kesintiye uğramadan) bu dosyayı alır.
- Hastanın zihni okunmaya devam ederken araba giderken bile, model yapay zeka motorunda *sıcak değişim (hot-swap)* ile saniyenin onda biri hızında değiştirilir. Sistemin kapatılıp açılmasına gerek kalmaz.

---

### 🔥 Sistemin Sağlamlık Testi
Arka planda eklediğimiz onlarca matematiksel kodu ve filtreyi "acaba bozuldu mu?" diye saniyeler içinde kontrol etmek istediğinde:

```bash
python3 -m wheelchair_bci.bench_test
```
Bu komut 36 farklı kaza senaryosunu (göz kırpma, bağlantı kopması Arduino bozulması vb.) donanıma ihtiyaç duymadan simüle eder ve hepsini geçtiğini doğrular.

> Not: Sen sadece yukarıdaki giriş kapılarını (main dosyalarını) çalıştırırsın. Geri kalan tüm işi (`ads1299.py`, `smoother.py`, `lead_off.py`, `ui.py` vb.) bu giriş kapıları kendi içlerinde bir saat gibi orkestre eder.
