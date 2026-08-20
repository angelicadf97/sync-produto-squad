@echo off
REM Gera todos os .exe em dist\ (precisa ser rodado num Windows com Python instalado).
pip install -r requirements.txt pyinstaller

pyinstaller --onefile --windowed --name SyncProdutoSquad --distpath dist --workpath build gui.py
pyinstaller --onefile --console  --name sync-prazo --distpath dist --workpath build sync-prazo.py
pyinstaller --onefile --console  --name tempo-status --distpath dist --workpath build tempo-status.py
pyinstaller --onefile --console  --name corrige-datas-fechadas --distpath dist --workpath build corrige-datas-fechadas.py
pyinstaller --onefile --console  --name configurar --distpath dist --workpath build configurar.py

copy config.json dist\config.json

echo.
echo Pronto! A pasta dist\ tem tudo que precisa: SyncProdutoSquad.exe + os .exe auxiliares + config.json.
echo Distribua a pasta dist\ inteira (renomeie se quiser) — os arquivos precisam ficar juntos.
pause
