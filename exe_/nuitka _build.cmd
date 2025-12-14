pythons -m nuitka ^
 --standalone ^
 --onefile ^
 --remove-output ^
 --include-package=pypresence ^
 --plugin-enable=pyside6 ^
 --windows-console-mode=disable ^
 --windows-icon-from-ico=icon.ico ^
 --mingw64 ^
 --show-scons ^
 --include-data-file=index.html=index.html ^
 --include-data-file=icon.ico=icon.ico ^
 --include-data-file=AudioEZGirl.png=AudioEZGirl.png ^
 --include-data-file=config.py=config.py ^
 --include-data-file=config_manager.py=config_manager.py ^
 --include-data-file=config_save.py=config_save.py ^
 --include-data-file=python_channel.py=python_channel.py ^
 --include-data-file=verification.py=verification.py ^
 --include-data-file=audio_engine.py=audio_engine.py ^
 main.py

pause > nul