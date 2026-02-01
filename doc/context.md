flowchart TB
  user[iOS Nutzer\n(Fotos hinzufügen/entfernen)]
  immichApp[iOS Immich App]
  fs[framework-server\nImmich]
  dbk[DBK Client\n(Raspberry Pi + Display)]
  ts[Tailscale\n(VPN / MagicDNS)]
  album[Immich Album\n"Digi Kalender Ana"\n(shared)]

  user --> immichApp
  immichApp -->|upload / manage album| fs
  fs --> album

  dbk <-->|encrypted tunnel| ts
  ts <-->|encrypted tunnel| fs

  dbk -->|shows photos from album| album
