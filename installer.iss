; Inno Setup — instalador de Vocal Remover Desktop
;
; Empaqueta el runtime portable + la app + binarios en un único Setup.exe.
; Instalación por-usuario (sin admin) en %LOCALAPPDATA%\Programs\VocalRemover,
; para que el auto-update (Fase 3) pueda reemplazar archivos sin permisos de
; administrador y para evitar prompts de UAC.
;
; Requiere Inno Setup 6.1+ (usa CreateDownloadPage). Compilar con:
;   & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss

#define AppName "Vocal Remover"
#define AppVersion "1.0.5"

; Pesos del modelo Demucs por defecto (mdx_extra). Se descargan durante la
; instalación en vez de la primera ejecución: la espera ocurre donde el usuario
; ya espera que algo tarde, con barra de progreso real, y la app queda usable
; apenas termina de instalarse.
;
; Los cuatro archivos y la URL salen de la propia librería:
;   demucs/pretrained.py -> ROOT_URL
;   demucs/remote/files.txt -> "root: mdx_final/"
;   demucs/remote/mdx_extra.yaml -> las 4 firmas del bag
; Van a la caché de torch.hub, que desktop.py apunta con TORCH_HOME.
#define ModelRoot "https://dl.fbaipublicfiles.com/demucs/mdx_final/"
#define ModelDir  "{localappdata}\VocalRemover\models\hub\checkpoints"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Alex Reineck
DefaultDirName={localappdata}\Programs\VocalRemover
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist_installer
OutputBaseFilename=VocalRemover-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos adicionales:"
; Desmarcable a propósito: permite instalar sin conexión, o no volver a bajar
; los pesos si ya están en la caché de una instalación anterior.
Name: "modelo"; Description: "Descargar ahora el modelo de IA (~640 MB)"; GroupDescription: "Preparación:"

[Files]
Source: "runtime\*";      DestDir: "{app}\runtime"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "app\*";          DestDir: "{app}\app";     Excludes: "__pycache__\*,__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "bin\ffmpeg.exe"; DestDir: "{app}\bin";     Flags: ignoreversion
Source: "bin\yt-dlp.exe"; DestDir: "{app}\bin";     Flags: ignoreversion
Source: "assets\icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "desktop.py";     DestDir: "{app}";         Flags: ignoreversion
Source: "version.txt";    DestDir: "{app}";         Flags: ignoreversion

; Pesos descargados en tiempo de instalación (ver [Code]). No van dentro del
; Setup.exe: "external" los toma de {tmp}. "skipifsourcedoesntexist" hace que
; una descarga omitida o fallida no aborte la instalación — la app los baja
; sola en la primera ejecución.
Source: "{tmp}\e51eebcc-c1b80bdd.th"; DestDir: "{#ModelDir}"; Flags: external skipifsourcedoesntexist ignoreversion; Tasks: modelo
Source: "{tmp}\a1d90b5c-ae9d2452.th"; DestDir: "{#ModelDir}"; Flags: external skipifsourcedoesntexist ignoreversion; Tasks: modelo
Source: "{tmp}\5d2d6c55-db83574e.th"; DestDir: "{#ModelDir}"; Flags: external skipifsourcedoesntexist ignoreversion; Tasks: modelo
Source: "{tmp}\cfa93e08-61801ae1.th"; DestDir: "{#ModelDir}"; Flags: external skipifsourcedoesntexist ignoreversion; Tasks: modelo

[Icons]
Name: "{group}\{#AppName}";        Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\desktop.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\desktop.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\desktop.py"""; WorkingDir: "{app}"; Description: "Iniciar {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Limpia cachés/artefactos que la app crea dentro de su carpeta (si los hubiera).
; Los pesos del modelo NO se borran: viven en %LOCALAPPDATA%\VocalRemover y
; reinstalar sin volver a bajar 640 MB es lo que uno espera.
Type: filesandordirs; Name: "{app}\app\__pycache__"

[Code]
var
  DownloadPage: TDownloadWizardPage;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(
    'Descargando el modelo de IA',
    'Se están descargando los pesos de Demucs (unos 640 MB). Al terminar, la aplicación queda lista para usar sin más esperas.',
    @OnDownloadProgress);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  if (CurPageID = wpReady) and WizardIsTaskSelected('modelo') then
  begin
    // Si ya están en la caché (reinstalación), no tiene sentido bajarlos otra vez.
    if FileExists(ExpandConstant('{#ModelDir}\e51eebcc-c1b80bdd.th')) and
       FileExists(ExpandConstant('{#ModelDir}\a1d90b5c-ae9d2452.th')) and
       FileExists(ExpandConstant('{#ModelDir}\5d2d6c55-db83574e.th')) and
       FileExists(ExpandConstant('{#ModelDir}\cfa93e08-61801ae1.th')) then
    begin
      Log('Los pesos del modelo ya están en la caché; se omite la descarga.');
      Exit;
    end;

    DownloadPage.Clear;
    DownloadPage.Add('{#ModelRoot}e51eebcc-c1b80bdd.th', 'e51eebcc-c1b80bdd.th', '');
    DownloadPage.Add('{#ModelRoot}a1d90b5c-ae9d2452.th', 'a1d90b5c-ae9d2452.th', '');
    DownloadPage.Add('{#ModelRoot}5d2d6c55-db83574e.th', '5d2d6c55-db83574e.th', '');
    DownloadPage.Add('{#ModelRoot}cfa93e08-61801ae1.th', 'cfa93e08-61801ae1.th', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
      except
        // Fallar la descarga no debe abortar la instalación: la app sabe
        // bajarlos sola en la primera ejecución, mostrando su propio progreso.
        Log('Falló la descarga del modelo: ' + GetExceptionMessage);
        Result := SuppressibleMsgBox(
          'No se pudo descargar el modelo de IA:' + #13#10#13#10 +
          GetExceptionMessage + #13#10#13#10 +
          '¿Querés continuar igual? La aplicación lo descargará sola la primera vez que la abras.',
          mbConfirmation, MB_YESNO, IDYES) = IDYES;
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;
