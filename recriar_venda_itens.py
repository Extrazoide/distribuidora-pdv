import sqlite3
import os

DB_PATH = r"D:\Sistema\banco.db"

def recriar_venda_itens():
    if not os.path.exists(DB_PATH):
        print("❌ Banco não encontrado:", DB_PATH)
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF;")  # Desativa temporariamente para recriar
    c = conn.cursor()

    # 1️⃣ Verifica se a tabela existe
    tabelas = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "venda_itens" not in tabelas:
        print("⚠️ Tabela 'venda_itens' não existe — será criada nova.")
    else:
        print("🔄 Recriando tabela 'venda_itens' com ON DELETE CASCADE...")

        # 2️⃣ Cria tabela temporária nova com FK em cascata
        c.execute("""
        CREATE TABLE nova_venda_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venda_id INTEGER,
            produto_id INTEGER,
            produto_nome TEXT,
            quantidade INTEGER,
            preco_unitario REAL,
            data_hora TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (venda_id) REFERENCES caixa(id) ON DELETE CASCADE,
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        )
        """)

        # 3️⃣ Copia dados antigos, se existirem
        try:
            c.execute("SELECT COUNT(*) FROM venda_itens")
            c.execute("""
                INSERT INTO nova_venda_itens (id, venda_id, produto_id, produto_nome, quantidade, preco_unitario, data_hora)
                SELECT id, venda_id, produto_id, produto_nome, quantidade, preco_unitario, data_hora
                FROM venda_itens
            """)
            print("✅ Dados antigos migrados com sucesso.")
        except Exception as e:
            print("⚠️ Nenhum dado copiado (tabela antiga vazia ou incompatível).", e)

        # 4️⃣ Remove a antiga e renomeia a nova
        c.execute("DROP TABLE venda_itens;")
        c.execute("ALTER TABLE nova_venda_itens RENAME TO venda_itens;")

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.close()
    print("✅ Tabela 'venda_itens' atualizada com sucesso (ON DELETE CASCADE ativo).")


if __name__ == "__main__":
    recriar_venda_itens()
