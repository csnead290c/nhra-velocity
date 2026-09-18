from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hidden_launcher_is_offline_first_and_does_not_mutate_install():
    text = (ROOT / 'scripts' / 'Launch-NHRA-Velocity-Dev.cmd').read_text(encoding='utf-8').lower()
    assert 'git -c' not in text
    assert 'git fetch' not in text
    assert 'git pull' not in text
    assert 'pip install' not in text
    assert 'pythonw.exe' in text
    assert 'desktop.py' in text


def test_visible_diagnostic_launcher_exists():
    text = (ROOT / 'scripts' / 'Launch-NHRA-Velocity-Diagnostic.cmd').read_text(encoding='utf-8').lower()
    assert 'python.exe' in text
    assert 'desktop.py' in text
    assert 'pause' in text


def test_protected_startup_shows_shell_before_sign_in():
    text = (ROOT / 'desktop.py').read_text(encoding='utf-8')
    marker = "logging.info('Tech Services sign-in required before protected startup')"
    i = text.index(marker)
    j = text.index('if not win._sign_in():', i)
    block = text[i:j]
    assert 'win.show()' in block
    assert 'app.processEvents()' in block
