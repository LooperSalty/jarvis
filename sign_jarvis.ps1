# Signe Jarvis.exe avec un certificat auto-signe.
#
# IMPORTANT — ce que ca fait et ne fait PAS :
#  - Cree (1 fois) un certificat de signature de code auto-signe "LooperSalty Jarvis"
#    et l'enregistre comme AUTORITE DE CONFIANCE pour TON compte Windows.
#    => sur CE PC, l'exe apparait comme signe et de confiance (moins de faux positifs).
#  - Ca ne supprime PAS les avertissements SmartScreen sur LES AUTRES PC : une vraie
#    distribution sans alerte exige un certificat OV/EV paye (~200-400 $/an) delivre
#    par une autorite (DigiCert, Sectigo...). Un certificat auto-signe n'est de
#    confiance que la ou on l'a explicitement installe.
#
# Usage : powershell -ExecutionPolicy Bypass -File sign_jarvis.ps1

$ErrorActionPreference = "Stop"
$subject = "CN=LooperSalty Jarvis"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1) Recupere ou cree le certificat de signature de code
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -eq $subject } | Select-Object -First 1
if (-not $cert) {
    Write-Host "Creation du certificat auto-signe..."
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject `
        -CertStoreLocation Cert:\CurrentUser\My -KeyUsage DigitalSignature `
        -KeyExportPolicy Exportable -NotAfter (Get-Date).AddYears(5)
}

# Exporte le .cer public a cote du script (a installer manuellement pour approuver).
$cer = Join-Path $root "jarvis_codesign.cer"
Export-Certificate -Cert $cert -FilePath $cer | Out-Null

# NB : on n'ajoute PAS automatiquement le certificat au magasin "Trusted Root" :
# Windows exige une confirmation interactive (securite) et le faire en script
# peut bloquer. Pour approuver le certificat sur CE PC (une seule fois) :
#   double-clique 'jarvis_codesign.cer' -> Installer le certificat ->
#   Utilisateur actuel -> "Placer tous les certificats dans le magasin suivant"
#   -> Autorites de certification racines de confiance -> OK.
# Apres ca, Jarvis.exe apparait comme signe et de confiance sur ta machine.

# 2) Signe les exe presents (racine + dist).
# Horodatage opt-in (-Timestamp) : sinon on signe sans, ce qui suffit pour la
# confiance locale et evite de dependre d'un serveur de timestamp parfois lent.
$signArgs = @{ HashAlgorithm = "SHA256" }
if ($env:JARVIS_SIGN_TIMESTAMP -eq "1") {
    $signArgs["TimestampServer"] = "http://timestamp.digicert.com"
}
$targets = @("Jarvis.exe", "dist\Jarvis.exe") | ForEach-Object { Join-Path $root $_ } |
           Where-Object { Test-Path $_ }
foreach ($exe in $targets) {
    $res = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert @signArgs
    Write-Host ("{0} -> {1}" -f (Split-Path $exe -Leaf), $res.Status)
}
