ILK PUBLISHABLE BELLA CANVAS 3001 ASSET'I

Bu klasor gercek urunun fotografini bekliyor. AI uretimi DEGIL.

TAM YONERGE: SOP-GercekBC3001.md

OZET SIRALAMA
  1. base.png        gercek BC3001 fotografi (kisa kenar >= 2400 px)
  2. auto_mask.py    --method cloth
  3. quad hesabi     govde genisligi olculur, 12x16 inc piksele cevrilir
  4. calibrate_quad.py --points <hesaplanan>
  5. prepare_base.py
  6. cli.py          kalibrasyon
  7. verify_recolor.py

KABUL KRITERLERI (hepsi gecmeden publishable=true YAPMA)
  garment_mask kaplama    %25 - 60
  kivrim std              > 6      (ideal > 15)
  kivrim/gurultu          > 1.5
  golge araligi           > 50 seviye
  print_mask tasan piksel = 0
  baski disi degisim      = 0 piksel

META ALANLARI
  source_detail    cekim tarihi/yeri, model onayi alindi mi
  verified_garment elindeki gercekten BC3001 mi
  publishable      kabul kriterleri gecince true
  created          cekim tarihi
