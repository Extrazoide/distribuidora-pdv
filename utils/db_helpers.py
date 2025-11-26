import sqlite3
import os
import time
from werkzeug.security import generate_password_hash

DB_DIR = "/var/data"
DB_PATH = os.path.join(DB_DIR, "banco.db")

storage_ready = False
global_conn = None


# ============================================================
# 🔥 Certifica que /var/data existe (roda uma vez só)
# ============================================================
def prepare_storage_once():
    global storage_ready, DB_PATH

    if storage_ready:
        return

    for _ in range(40):
        try:
            if not os.path.exists(DB_DIR):
                os.makedirs(DB_DIR, exist_ok=True)

            tmp = os.path.join(DB_DIR, "test.tmp")
            with open(tmp, "w") as f:
                f.write("OK")
            os.remove(tmp)

            storage_ready = True
            return

        except Exception:
            time.sleep(0.2)

    print("⚠️ /var/data indisponível — usando banco local")
    DB_PATH = os.path.join(os.getcwd(), "banco.db")
    storage_ready = True


# ============================================================
# 🔥 Função para criar conexão
# ============================================================
def create_connection():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")

    return conn


# ============================================================
# 🔥 CONEXÃO GLOBAL (com auto-reconstrução)
# ============================================================
def get_db_connection():
    global global_conn
    prepare_storage_once()

    # 1. Não existe ainda?
    if global_conn is None:
        global_conn = create_connection()
        return global_conn

    # 2. Existe mas foi fechada pelo sistema?
    try:
        global_conn.execute("SELECT 1;")
    except sqlite3.ProgrammingError:
        print("⚠️ Conexão SQLite estava fechada. Reconectando...")
        global_conn = create_connection()

    return global_conn



# ============================================================
# 🔥 CRIA BANCO SÓ SE NÃO EXISTIR
# ============================================================
def init_db():
    """
    Cria as tabelas apenas uma vez.
    Não sobrescreve banco existente.
    """
    prepare_storage_once()

    if os.path.exists(DB_PATH):
        return  # NÃO recriar banco

    print(f"📌 Criando banco pela primeira vez em: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # --------------------------------
    # Usuários
    # --------------------------------
    c.execute("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'attendant'
    )
    """)

    # Configurações gerais
    c.execute("""
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    c.execute("INSERT INTO settings (key, value) VALUES (?, ?)",
              ("commerce_name", "ROYAL BEBIDAS"))

    # Admin padrão
    admin_pw = generate_password_hash("1234")
    c.execute("""
        INSERT INTO users (username, password_hash, role)
        VALUES (?,?,?)
    """, ("admin", admin_pw, "admin"))

    # --------------------------------
    # Produtos
    # --------------------------------
    c.execute("""
    CREATE TABLE produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo_barra TEXT UNIQUE NOT NULL,
        nome TEXT NOT NULL,
        preco REAL NOT NULL,
        estoque INTEGER NOT NULL,
        categoria TEXT DEFAULT 'Outros',
        ativo INTEGER DEFAULT 1
    )
    """)

    # --------------------------------
    # Pedidos
    # --------------------------------
    c.execute("""
    CREATE TABLE pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER,
        quantidade INTEGER,
        status TEXT DEFAULT 'aberta',
        usuario TEXT DEFAULT 'Desconhecido',
        FOREIGN KEY (produto_id) REFERENCES produtos(id)
    )
    """)

    # --------------------------------
    # Comandas
    # --------------------------------
    c.execute("""
    CREATE TABLE comandas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero TEXT UNIQUE NOT NULL,
        cliente TEXT,
        observacao TEXT,
        status TEXT DEFAULT 'aberta',
        total REAL DEFAULT 0,
        desconto REAL DEFAULT 0,
        recebido REAL DEFAULT 0,
        troco REAL DEFAULT 0,
        usuario TEXT DEFAULT 'Desconhecido'
    )
    """)

    # Itens da comanda
    c.execute("""
    CREATE TABLE comanda_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        comanda_id INTEGER,
        produto_id INTEGER,
        quantidade INTEGER,
        preco_unitario REAL,
        FOREIGN KEY (comanda_id) REFERENCES comandas(id),
        FOREIGN KEY (produto_id) REFERENCES produtos(id)
    )
    """)

    # --------------------------------
    # Caixa
    # --------------------------------
    c.execute("""
    CREATE TABLE caixa (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_hora TEXT DEFAULT (datetime('now','localtime')),
        total REAL,
        desconto REAL,
        recebido REAL,
        troco REAL,
        forma_pagamento TEXT DEFAULT 'Dinheiro',
        usuario TEXT DEFAULT 'Desconhecido'
    )
    """)

    # --------------------------------
    # Fechamentos
    # --------------------------------
    c.execute("""
    CREATE TABLE fechamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_hora TEXT DEFAULT (datetime('now','localtime')),
        usuario TEXT,
        turno TEXT,
        total_vendas REAL,
        total_descontos REAL,
        total_recebido REAL,
        total_troco REAL,
        total_liquido REAL,
        observacao TEXT
    )
    """)

    # --------------------------------
    # Pagamentos
    # --------------------------------
    c.execute("""
    CREATE TABLE pagamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id INTEGER,
        comanda_id INTEGER,
        forma_pagamento TEXT,
        valor REAL,
        data_hora TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (venda_id) REFERENCES caixa(id),
        FOREIGN KEY (comanda_id) REFERENCES comandas(id)
    )
    """)

    # --------------------------------
    # Cancelamentos
    # --------------------------------
    c.execute("""
    CREATE TABLE cancelamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER,
        nome TEXT,
        quantidade INTEGER,
        preco_unitario REAL,
        usuario TEXT,
        data_hora TEXT DEFAULT (datetime('now','localtime'))
    )
    """)

    # --------------------------------
    # Itens da venda
    # --------------------------------
    c.execute("""
    CREATE TABLE venda_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id INTEGER,
        produto_id INTEGER,
        produto_nome TEXT,
        quantidade INTEGER,
        preco_unitario REAL,
        usuario TEXT DEFAULT '',
        data_hora TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (venda_id) REFERENCES caixa(id),
        FOREIGN KEY (produto_id) REFERENCES produtos(id)
    )
    """)

    conn.commit()
    conn.close()


# ============================================================
# 🔥 MIGRAÇÃO
# ============================================================
def init_db_custom():
    init_db()


# ============================================================
# 🔧 Funções utilitárias
# ============================================================
def get_setting(key, default=None):
    conn = get_db_connection()
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(key, value):
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, value))
    conn.commit()

