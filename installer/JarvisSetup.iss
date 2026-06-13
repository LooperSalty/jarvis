; ============================================================
; Installateur Windows de Jarvis (Inno Setup 6.3+)
; ============================================================
; Compile : scripts\build_installer.bat
;   (ou : ISCC /DAppVersion=x.y.z installer\JarvisSetup.iss)
; Prerequis de compilation (builds ONEDIR) : presents dans {#BinDir} (la racine
; du repo par defaut, ou passe /DBinDir=chemin) -> Jarvis.exe + dossier _internal\,
; JarvisWeb.exe + dossier _internal_web\ (optionnel), ModelAdvisor.exe (onefile,
; optionnel). build_all.bat / release.yml y deversent dist\Jarvis\* et
; dist\JarvisWeb\*. Produit installer\output\JarvisSetup-<version>.exe.
;
; Choix structurants :
; - Installation PAR UTILISATEUR ({localappdata}\Programs\Jarvis), sans admin :
;   Jarvis persiste ses donnees (memoire, profil, .env...) A COTE du .exe,
;   le dossier doit donc etre inscriptible par l'utilisateur. Ne JAMAIS
;   basculer vers Program Files sans revoir _dossier_donnees() partout.
; - Composant optionnel "Cerveau local" : telecharge OllamaSetup.exe depuis
;   ollama.com, l'installe silencieusement, puis tire un modele au choix.
;   Tout echec reseau est NON bloquant (le dashboard sait installer les
;   modeles plus tard, section "Modele IA").
; - Bilingue : francais / anglais (texte custom dans [CustomMessages]).

; --- Version : passee par /DAppVersion, sinon lue dans jarvis_version.py ---
#ifndef AppVersion
  #define _VerFichier = FileOpen(AddBackslash(SourcePath) + "..\jarvis_version.py")
  #if _VerFichier == 0
    #pragma error "jarvis_version.py introuvable a cote du dossier installer/"
  #endif
  #define _Ligne = ""
  #define AppVersion = ""
  ; NB : dans le corps d'un #sub, les reassignations doivent etre des #expr —
  ; un #define n'y est pas execute (ISPP), la boucle resterait sans effet.
  #sub _LireLigneVersion
    #expr _Ligne = FileRead(_VerFichier)
    #if (AppVersion == "") && (Pos('VERSION = "', _Ligne) == 1)
      #expr AppVersion = Copy(_Ligne, 12, Pos('"', Copy(_Ligne, 12, 100)) - 1)
    #endif
  #endsub
  #for {0; !FileEof(_VerFichier); 0} _LireLigneVersion
  #expr FileClose(_VerFichier)
  #if AppVersion == ""
    #pragma error "VERSION introuvable dans jarvis_version.py (format attendu : VERSION = ""x.y.z"")"
  #endif
#endif

; --- Dossier des binaires a embarquer (relatif au .iss) ---
#ifndef BinDir
  #define BinDir ".."
#endif

#if !FileExists(AddBackslash(SourcePath) + AddBackslash(BinDir) + "Jarvis.exe")
  #pragma error "Jarvis.exe introuvable dans " + BinDir + " : lance build_all.bat d'abord"
#endif
#define HasWeb     FileExists(AddBackslash(SourcePath) + AddBackslash(BinDir) + "JarvisWeb.exe")
#define HasAdvisor FileExists(AddBackslash(SourcePath) + AddBackslash(BinDir) + "ModelAdvisor.exe")

[Setup]
AppId={{4F8E7C21-9B5D-4A36-8F0E-2D7C1A93B6E4}
AppName=Jarvis
AppVersion={#AppVersion}
AppVerName=Jarvis {#AppVersion}
AppPublisher=LooperSalty
AppPublisherURL=https://github.com/LooperSalty/jarvis
AppSupportURL=https://github.com/LooperSalty/jarvis/issues
AppUpdatesURL=https://github.com/LooperSalty/jarvis/releases
VersionInfoVersion={#AppVersion}
; Par utilisateur, sans elevation : les donnees vivent a cote de l'exe.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Jarvis
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=output
OutputBaseFilename=JarvisSetup-{#AppVersion}
SetupIconFile=..\assets\jarvis.ico
UninstallDisplayIcon={app}\Jarvis.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Types]
Name: "full"; Description: "{cm:TypeFull}"
Name: "compact"; Description: "{cm:TypeCompact}"
Name: "custom"; Description: "{cm:TypeCustom}"; Flags: iscustom

[Components]
Name: "core"; Description: "{cm:CompCore}"; Types: full compact custom; Flags: fixed
#if HasWeb
Name: "web"; Description: "{cm:CompWeb}"; Types: full
#endif
#if HasAdvisor
Name: "advisor"; Description: "{cm:CompAdvisor}"; Types: full
#endif
Name: "ollama"; Description: "{cm:CompOllama}"; Types: full

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutoStartDesc}"; GroupDescription: "{cm:OptionsGroup}"; Flags: unchecked

[Files]
; Builds ONEDIR : Jarvis.exe / JarvisWeb.exe restent a la RACINE de {app} (pour
; que _dossier_donnees() = Path(sys.executable).parent pointe sur {app} et que
; les deux exes partagent .env / memoire / profil), et chaque exe a son dossier
; de contenu DISTINCT (_internal / _internal_web) copie a cote. BinDir contient
; donc Jarvis.exe + _internal\ + JarvisWeb.exe + _internal_web\ (cf. build_all.bat
; et l'etape "Compiler l'installateur" de release.yml qui y deversent les
; dossiers dist\Jarvis\* et dist\JarvisWeb\*).
Source: "{#BinDir}\Jarvis.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "{#BinDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: core
#if HasWeb
Source: "{#BinDir}\JarvisWeb.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: web
Source: "{#BinDir}\_internal_web\*"; DestDir: "{app}\_internal_web"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: web
#endif
#if HasAdvisor
Source: "{#BinDir}\ModelAdvisor.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: advisor
#endif
; Modele de configuration : le dashboard ecrit le vrai .env a cote de l'exe.
Source: "..\.env.example"; DestDir: "{app}"; Flags: ignoreversion; Components: core

[Icons]
Name: "{userprograms}\Jarvis"; Filename: "{app}\Jarvis.exe"
#if HasWeb
Name: "{userprograms}\Jarvis (mode web)"; Filename: "{app}\JarvisWeb.exe"; Components: web
#endif
#if HasAdvisor
Name: "{userprograms}\ModelAdvisor"; Filename: "{app}\ModelAdvisor.exe"; Components: advisor
#endif
Name: "{userdesktop}\Jarvis"; Filename: "{app}\Jarvis.exe"; Tasks: desktopicon

[Registry]
; Demarrage automatique avec Windows (tache optionnelle, decochee par defaut)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "Jarvis"; ValueData: """{app}\Jarvis.exe"""; \
  Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\Jarvis.exe"; Description: "{cm:LaunchProgram,Jarvis}"; \
  Flags: nowait postinstall skipifsilent

[CustomMessages]
english.TypeFull=Full installation (recommended)
english.TypeCompact=Minimal installation (Jarvis only)
english.TypeCustom=Custom installation
english.CompCore=Jarvis (main application)
english.CompWeb=JarvisWeb — browser mode (no dedicated window)
english.CompAdvisor=ModelAdvisor — which local model fits my PC?
english.CompOllama=Local AI brain — install Ollama + a model (recommended)
english.OptionsGroup=Other options:
english.AutoStartDesc=Start Jarvis automatically when Windows starts
english.ModelPageCaption=Local AI model
english.ModelPageDesc=Choose the model Jarvis will use offline
english.ModelPageSub=The model is downloaded by Ollama after installation. You can install other models later from the Jarvis dashboard ("AI Model" section), which can also recommend the best model for your hardware.
english.ModelLight=llama3.2:3b — light and fast, ~2 GB (any PC, 8 GB RAM)
english.ModelReco=qwen2.5:7b — better quality, ~4.7 GB (16 GB RAM advised)
english.ModelCode=deepseek-coder-v2:lite — code oriented, ~8.9 GB (16 GB RAM + GPU advised)
english.ModelNone=No model now (install one later from the dashboard)
english.OllamaDownloadFailed=Ollama could not be downloaded (no network?). Jarvis will still be installed: you can install Ollama later from https://ollama.com and pick a model from the Jarvis dashboard.
english.InstallingOllama=Installing Ollama (local AI engine)...
english.PullingModel=Downloading the AI model — progress is shown in the console window. This can take several minutes depending on your connection.
english.ModelPullFailed=The model could not be downloaded. You can install it later from the Jarvis dashboard ("AI Model" section) once Ollama is running.
english.RemoveDataPrompt=Also delete Jarvis data (memory, profile, .env keys, history, skills)?%nChoose "No" to keep them for a future installation.
french.TypeFull=Installation complète (recommandée)
french.TypeCompact=Installation minimale (Jarvis seul)
french.TypeCustom=Installation personnalisée
french.CompCore=Jarvis (application principale)
french.CompWeb=JarvisWeb — mode navigateur (sans fenêtre dédiée)
french.CompAdvisor=ModelAdvisor — quel modèle local pour mon PC ?
french.CompOllama=Cerveau IA local — installer Ollama + un modèle (recommandé)
french.OptionsGroup=Autres options :
french.AutoStartDesc=Lancer Jarvis automatiquement au démarrage de Windows
french.ModelPageCaption=Modèle d'IA local
french.ModelPageDesc=Choisissez le modèle que Jarvis utilisera hors-ligne
french.ModelPageSub=Le modèle est téléchargé par Ollama après l'installation. Vous pourrez installer d'autres modèles plus tard depuis le dashboard de Jarvis (section « Modèle IA »), qui sait aussi recommander le meilleur modèle pour votre machine.
french.ModelLight=llama3.2:3b — léger et rapide, ~2 Go (tout PC, 8 Go de RAM)
french.ModelReco=qwen2.5:7b — meilleure qualité, ~4,7 Go (16 Go de RAM conseillés)
french.ModelCode=deepseek-coder-v2:lite — orienté code, ~8,9 Go (16 Go RAM + GPU conseillés)
french.ModelNone=Aucun modèle maintenant (installation plus tard via le dashboard)
french.OllamaDownloadFailed=Ollama n'a pas pu être téléchargé (pas de réseau ?). Jarvis sera quand même installé : vous pourrez installer Ollama plus tard depuis https://ollama.com et choisir un modèle dans le dashboard de Jarvis.
french.InstallingOllama=Installation d'Ollama (moteur d'IA local)...
french.PullingModel=Téléchargement du modèle d'IA — la progression s'affiche dans la fenêtre console. Cela peut prendre plusieurs minutes selon votre connexion.
french.ModelPullFailed=Le modèle n'a pas pu être téléchargé. Vous pourrez l'installer plus tard depuis le dashboard de Jarvis (section « Modèle IA ») une fois Ollama démarré.
french.RemoveDataPrompt=Supprimer aussi les données de Jarvis (mémoire, profil, clés .env, historique, skills) ?%nChoisissez « Non » pour les conserver en vue d'une réinstallation.

[Code]
const
  URL_OLLAMA_SETUP = 'https://ollama.com/download/OllamaSetup.exe';

var
  PageModele: TInputOptionWizardPage;
  PageTelechargement: TDownloadWizardPage;
  OllamaSetupTelecharge: Boolean;

function CheminOllamaExe(): String;
begin
  Result := ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe');
end;

function CheminOllamaApp(): String;
begin
  Result := ExpandConstant('{localappdata}\Programs\Ollama\ollama app.exe');
end;

function OllamaDejaInstalle(): Boolean;
begin
  Result := FileExists(CheminOllamaExe());
end;

function NomModeleChoisi(): String;
begin
  case PageModele.SelectedValueIndex of
    0: Result := 'llama3.2:3b';
    1: Result := 'qwen2.5:7b';
    2: Result := 'deepseek-coder-v2:lite';
  else
    Result := ''; // « aucun modèle maintenant »
  end;
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if ProgressMax <> 0 then
    Log(Format('Telechargement %s : %d / %d', [FileName, Progress, ProgressMax]));
  Result := True;
end;

procedure InitializeWizard();
begin
  OllamaSetupTelecharge := False;

  // Page de choix du modele local (affichee seulement si composant "ollama")
  PageModele := CreateInputOptionPage(
    wpSelectComponents,
    CustomMessage('ModelPageCaption'),
    CustomMessage('ModelPageDesc'),
    CustomMessage('ModelPageSub'),
    True,   // exclusif (boutons radio)
    False);
  PageModele.Add(CustomMessage('ModelLight'));
  PageModele.Add(CustomMessage('ModelReco'));
  PageModele.Add(CustomMessage('ModelCode'));
  PageModele.Add(CustomMessage('ModelNone'));
  PageModele.SelectedValueIndex := 0;

  PageTelechargement := CreateDownloadPage(
    SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc),
    @OnDownloadProgress);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = PageModele.ID then
    Result := not WizardIsComponentSelected('ollama');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  // Juste avant l'installation : telecharger OllamaSetup.exe si necessaire.
  if (CurPageID = wpReady) and WizardIsComponentSelected('ollama')
     and (not OllamaDejaInstalle()) then
  begin
    PageTelechargement.Clear;
    PageTelechargement.Add(URL_OLLAMA_SETUP, 'OllamaSetup.exe', '');
    PageTelechargement.Show;
    try
      try
        PageTelechargement.Download;
        OllamaSetupTelecharge := True;
      except
        // Echec reseau NON bloquant : Jarvis s'installe quand meme.
        if PageTelechargement.AbortedByUser then
          Log('Telechargement Ollama annule par l''utilisateur')
        else
          MsgBox(CustomMessage('OllamaDownloadFailed'), mbInformation, MB_OK);
        OllamaSetupTelecharge := False;
      end;
    finally
      PageTelechargement.Hide;
    end;
  end;
end;

procedure InstallerOllamaEtModele();
var
  CodeRetour: Integer;
  Modele: String;
begin
  // 1) Installation silencieuse d'Ollama (son installeur est aussi un Inno Setup)
  if OllamaSetupTelecharge then
  begin
    WizardForm.StatusLabel.Caption := CustomMessage('InstallingOllama');
    WizardForm.ProgressGauge.Style := npbstMarquee;
    try
      if not Exec(ExpandConstant('{tmp}\OllamaSetup.exe'),
                  '/VERYSILENT /NORESTART /SUPPRESSMSGBOXES', '',
                  SW_SHOW, ewWaitUntilTerminated, CodeRetour) then
        Log('Lancement OllamaSetup.exe impossible : code ' + IntToStr(CodeRetour))
      else if CodeRetour <> 0 then
        Log('OllamaSetup.exe a retourne ' + IntToStr(CodeRetour));
    finally
      WizardForm.ProgressGauge.Style := npbstNormal;
    end;
  end;

  // 2) Telechargement du modele choisi (progression native dans la console)
  Modele := NomModeleChoisi();
  if (Modele <> '') and FileExists(CheminOllamaExe()) then
  begin
    // Demarre le serveur Ollama (app tray, single-instance, sans danger si deja lance)
    if FileExists(CheminOllamaApp()) then
    begin
      Exec(CheminOllamaApp(), '', '', SW_HIDE, ewNoWait, CodeRetour);
      Sleep(4000); // laisse le serveur ecouter sur :11434
    end;
    WizardForm.StatusLabel.Caption := CustomMessage('PullingModel');
    WizardForm.ProgressGauge.Style := npbstMarquee;
    try
      if (not Exec(CheminOllamaExe(), 'pull ' + Modele, '',
                   SW_SHOW, ewWaitUntilTerminated, CodeRetour)) or (CodeRetour <> 0) then
      begin
        // Une seule relance : le serveur peut mettre du temps a demarrer.
        Sleep(5000);
        if (not Exec(CheminOllamaExe(), 'pull ' + Modele, '',
                     SW_SHOW, ewWaitUntilTerminated, CodeRetour)) or (CodeRetour <> 0) then
          MsgBox(CustomMessage('ModelPullFailed'), mbInformation, MB_OK);
      end;
    finally
      WizardForm.ProgressGauge.Style := npbstNormal;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // En mode silencieux, le telechargement d'Ollama (NextButtonClick) n'a pas
  // lieu : on saute aussi le pull du modele (pas de console surprise dans un
  // deploiement sans assistance — installation via le dashboard ensuite).
  if (CurStep = ssPostInstall) and WizardIsComponentSelected('ollama')
     and (not WizardSilent()) then
    InstallerOllamaEtModele();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App: String;
begin
  // Apres desinstallation des fichiers : proposer de supprimer les donnees
  // perso restees a cote de l'exe. Liste EXPLICITE (en phase avec
  // _dossier_donnees() cote Python) — jamais de DelTree global : l'utilisateur
  // a pu installer dans un dossier preexistant contenant d'autres fichiers.
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent()) then
  begin
    if MsgBox(CustomMessage('RemoveDataPrompt'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      App := ExpandConstant('{app}');
      DeleteFile(App + '\.env');
      DeleteFile(App + '\.env.example');
      DeleteFile(App + '\jarvis_memoire.json');
      DeleteFile(App + '\jarvis_memoire_vec.db');
      DeleteFile(App + '\jarvis_historique.json');
      DeleteFile(App + '\jarvis_profile.json');
      DeleteFile(App + '\jarvis_mcp.json');
      DeleteFile(App + '\jarvis_routines.json');
      DeleteFile(App + '\jarvis_triggers.json');
      DeleteFile(App + '\jarvis_ws_token.txt');
      DeleteFile(App + '\jarvis_home_config.py');
      DeleteFile(App + '\token.pickle');
      DeleteFile(App + '\credentials.json');
      DeleteFile(App + '\.spotify_cache');
      DelTree(App + '\jarvis_skills', True, True, True);
      // Ne supprime le dossier que s'il est VIDE — jamais les fichiers etrangers.
      RemoveDir(App);
    end;
  end;
end;
