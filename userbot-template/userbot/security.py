"""Session şifrələmə + plugin sandbox təhlükəsizliyi"""
import os
import base64
import ast
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from config import Config

def _key() -> bytes:
    raw = base64.urlsafe_b64decode(Config.ENCRYPTION_KEY.encode())
    if len(raw) != 32:
        raise RuntimeError("ENCRYPTION_KEY 32 bayt olmalıdır")
    return raw

def encrypt(text: str) -> str:
    aes = AESGCM(_key())
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, text.encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()

def decrypt(token: str) -> str:
    data = base64.urlsafe_b64decode(token.encode())
    return AESGCM(_key()).decrypt(data[:12], data[12:], None).decode()

# Qadağan olunmuş importlar (sandbox)
FORBIDDEN_IMPORTS = {
    "os.system", "subprocess", "ctypes", "shutil.rmtree",
    "pty", "pickle", "marshal", "importlib.reload",
}
FORBIDDEN_NAMES = {"exec", "compile", "__import__"}

def analyze_plugin(code: str) -> tuple[bool, str]:
    """Plugin kodunu statik analiz edir. (safe, reason)"""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Sintaksis xətası: {e}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if n.name in FORBIDDEN_IMPORTS or n.name.split(".")[0] in {"ctypes","pty","marshal"}:
                    return False, f"Qadağan modul: {n.name}"
        if isinstance(node, ast.ImportFrom):
            full = f"{node.module}.{node.names[0].name}" if node.module else ""
            if full in FORBIDDEN_IMPORTS:
                return False, f"Qadağan import: {full}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_NAMES:
                return False, f"Qadağan funksiya: {node.func.id}"
    return True, "OK"
