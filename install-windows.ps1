# Instala as dependências e configura o início automático no Windows.
# Uso: clique com botão direito neste arquivo > "Executar com PowerShell"
# (ou abra o PowerShell na pasta e rode: .\install-windows.ps1)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "== Verificando Python ==" -ForegroundColor Cyan
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python não encontrado." -ForegroundColor Red
    Write-Host "Instale em https://python.org/downloads (marque a caixinha 'Add python.exe to PATH' na instalação) e rode este script de novo."
    exit 1
}

Write-Host "== Verificando GitHub CLI (gh) ==" -ForegroundColor Cyan
$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Host "GitHub CLI (gh) não encontrado." -ForegroundColor Red
    Write-Host "Instale em https://cli.github.com e rode 'gh auth login' antes de usar o app."
    exit 1
}

Write-Host "== Instalando dependências Python ==" -ForegroundColor Cyan
pip install -r "$here\requirements.txt"

Write-Host "== Criando atalho de início automático ==" -ForegroundColor Cyan
$pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue)
$exe = if ($pythonw) { $pythonw.Source } else { $python.Source }

$wshell = New-Object -ComObject WScript.Shell

$startup = [Environment]::GetFolderPath("Startup")
$startupShortcut = $wshell.CreateShortcut((Join-Path $startup "Sync Produto x Squad.lnk"))
$startupShortcut.TargetPath = $exe
$startupShortcut.Arguments = "`"$here\gui.py`""
$startupShortcut.WorkingDirectory = $here
$startupShortcut.Save()

$programs = [Environment]::GetFolderPath("Programs")
$menuShortcut = $wshell.CreateShortcut((Join-Path $programs "Sync Produto x Squad.lnk"))
$menuShortcut.TargetPath = $exe
$menuShortcut.Arguments = "`"$here\gui.py`""
$menuShortcut.WorkingDirectory = $here
$menuShortcut.Save()

Write-Host ""
Write-Host "Pronto!" -ForegroundColor Green
Write-Host "Pra abrir agora: pythonw `"$here\gui.py`""
Write-Host "Da próxima vez que ligar o computador, o ícone já aparece sozinho na bandeja."
Write-Host "Também pode buscar 'Sync Produto x Squad' no menu Iniciar."
if (-not (Test-Path "$here\config.json")) {
    Write-Host "Ainda não tem nenhuma squad configurada — rode: python `"$here\configurar.py`""
}
