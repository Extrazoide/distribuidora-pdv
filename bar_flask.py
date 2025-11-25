from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from utils.auth_helpers import login_required, admin_required
from datetime import datetime
from io import BytesIO
import pandas as pd
from flask import send_file
import csv
import json
import sqlite3
from io import StringIO
from utils.db_helpers import get_db_connection, init_db, init_db_custom, get_setting, set_setting


from waitress import serve

app = Flask(__name__)
app.config["SECRET_KEY"] = "troque_esta_chave_por_uma_mais_secreta_em_producao"

# -------------------------
# Auth Routes
# -------------------------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash(f"Bem-vindo, {user['username']}!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Usuário ou senha inválidos.", "danger")
    return render_template("login.html", commerce=get_setting("commerce_name","ROYAL BEBIDAS"))

@app.route("/logout")
def logout():
    session.clear()
    flash("Você saiu.", "info")
    return redirect(url_for("login"))

# -------------------------
# Dashboard
# -------------------------
@app.route("/")
@login_required
def dashboard():
    commerce = get_setting("commerce_name","ROYAL BEBIDAS")
    return render_template("index.html", commerce=commerce)

# -------------------------
# Admin Panel
# -------------------------
@app.route("/admin")
@admin_required
def admin_panel():
    conn = get_db_connection()
    users = conn.execute("SELECT id, username, role FROM users").fetchall()
    conn.close()
    commerce = get_setting("commerce_name","ROYAL BEBIDAS")
    return render_template("admin.html", commerce=commerce, users=users)

@app.route("/ajax_verificar_admin", methods=["POST"])
def ajax_verificar_admin():
    """Verifica se a senha digitada pertence a um usuário admin."""
    data = request.get_json() or {}
    senha = data.get("senha", "")

    conn = get_db_connection()
    admin = conn.execute("SELECT password_hash FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    conn.close()

    if not admin or not check_password_hash(admin["password_hash"], senha):
        return jsonify({"status": "error", "msg": "Senha incorreta."})

    return jsonify({"status": "ok", "msg": "Admin verificado."})


@app.route("/admin/settings", methods=["POST"])
@admin_required
def admin_settings():
    nome = request.form.get("commerce_name", "").strip()
    if not nome:
        flash("O nome do comércio não pode ficar em branco.", "danger")
        return redirect(url_for("admin_panel"))

    set_setting("commerce_name", nome)
    flash("Nome do comércio atualizado com sucesso!", "success")
    return redirect(url_for("admin_panel"))

@app.route("/admin/add_user", methods=["POST"])
@admin_required
def admin_add_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "attendant")

    if not username or not password:
        flash("Usuário e senha são obrigatórios.", "danger")
        return redirect(url_for("admin_panel"))

    conn = get_db_connection()
    existente = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if existente:
        conn.close()
        flash("Já existe um usuário com esse nome.", "warning")
        return redirect(url_for("admin_panel"))

    password_hash = generate_password_hash(password)
    conn.execute("INSERT INTO users (username, password_hash, role) VALUES (?,?,?)", (username, password_hash, role))
    conn.commit()
    conn.close()
    flash("Usuário adicionado com sucesso!", "success")
    return redirect(url_for("admin_panel"))

@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    conn = get_db_connection()
    if user_id == session.get("user_id"):
        conn.close()
        flash("Você não pode excluir a si mesmo.", "warning")
        return redirect(url_for("admin_panel"))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash("Usuário excluído com sucesso!", "info")
    return redirect(url_for("admin_panel"))
@app.route("/admin/change_password", methods=["POST"])
@admin_required
def admin_change_password():
    user_id = request.form.get("user_id")
    nova_senha = request.form.get("nova_senha", "").strip()

    if not nova_senha:
        flash("A nova senha não pode estar vazia.", "warning")
        return redirect(url_for("admin_panel"))

    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(nova_senha), user_id)
    )
    conn.commit()
    conn.close()

    flash("Senha atualizada com sucesso!", "success")
    return redirect(url_for("admin_panel"))

# -------------------------
# Produtos & Vendas Routes (PDV)
# -------------------------
@app.route("/produtos")
@login_required
def produtos_page():
    conn = get_db_connection()
    produtos = conn.execute(
    "SELECT id, codigo_barra, nome, preco, estoque, categoria FROM produtos WHERE ativo = 1"
    ).fetchall()

    conn.close()
    return render_template("produtos.html", produtos=produtos, commerce=get_setting("commerce_name","ROYAL BEBIDAS"),role=session.get("role"))
# =========================================================
# 🔧 CRUD AJAX para Produtos

# 🔍 Pesquisa de produtos (para o campo AJAX)
@app.route("/ajax_buscar_produtos")
@login_required
def ajax_buscar_produtos():
    termo = request.args.get("q", "").strip()
    conn = get_db_connection()

    if termo:
        query = """
            SELECT id, codigo_barra, nome, preco, estoque, categoria
            FROM produtos
            WHERE ativo = 1
            AND (nome LIKE ? OR codigo_barra LIKE ?)
            ORDER BY nome LIMIT 100

        """
        produtos = conn.execute(query, (f"%{termo}%", f"%{termo}%")).fetchall()
    else:
        produtos = conn.execute("""
            SELECT id, codigo_barra, nome, preco, estoque, categoria
            FROM produtos
            WHERE ativo = 1
            ORDER BY nome LIMIT 100

        """).fetchall()

    conn.close()

    return jsonify([dict(p) for p in produtos])

# =========================================================
@app.route("/ajax_add_produto_produtos", methods=["POST"])
@login_required
def ajax_add_produto_produtos():
    """Adiciona novo produto via AJAX."""
    data = request.get_json()
    codigo = data.get("codigo", "").strip()
    categoria = data.get("categoria", "Outros").strip()
    nome = data.get("nome", "").strip()
    preco = float(data.get("preco", 0))
    estoque = int(data.get("estoque", 0))

    if not nome or preco <= 0:
        return jsonify({"status": "error", "msg": "Nome e preço são obrigatórios."})

    conn = get_db_connection()
    existente = conn.execute("SELECT id FROM produtos WHERE codigo_barra=?", (codigo,)).fetchone()
    if existente:
        conn.close()
        return jsonify({"status": "error", "msg": "Já existe um produto com este código."})

    conn.execute(
        "INSERT INTO produtos (codigo_barra, nome, preco, estoque, categoria) VALUES (?, ?, ?, ?, ?)",
        (codigo, nome, preco, estoque, categoria)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "msg": "Produto adicionado com sucesso!"})


@app.route("/ajax_editar_produto/<int:produto_id>", methods=["POST"])
@login_required
def ajax_editar_produto(produto_id):
    """Edita produto existente via AJAX."""
    data = request.get_json()
    codigo = data.get("codigo", "").strip()
    nome = data.get("nome", "").strip()
    preco = float(data.get("preco", 0))
    estoque = int(data.get("estoque", 0))

    conn = get_db_connection()
    categoria = data.get("categoria", "Outros").strip()

    conn.execute("""
        UPDATE produtos
        SET codigo_barra=?, nome=?, preco=?, estoque=?, categoria=?
        WHERE id=?
    """, (codigo, nome, preco, estoque, categoria, produto_id))

    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "msg": "Produto atualizado com sucesso!"})


@app.route("/ajax_remover_produto/<int:produto_id>", methods=["POST"])
@login_required
def ajax_remover_produto(produto_id):
    conn = get_db_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        # tenta excluir
        conn.execute("DELETE FROM produtos WHERE id=?", (produto_id,))
        conn.commit()
        conn.close()

        return jsonify({
            "status": "ok",
            "msg": "✅ Produto removido com sucesso!"
        })

    except Exception as e:
        conn.close()

        return jsonify({
            "status": "error",
            "msg": f"❌ Não foi possível remover. O produto está sendo usado em alguma venda, comanda ou cancelamento.\n\nDetalhes: {e}"
        })

@app.route("/ajax_desativar_produto/<int:produto_id>", methods=["POST"])
@login_required
def ajax_desativar_produto(produto_id):
    conn = get_db_connection()
    try:
        conn.execute("UPDATE produtos SET ativo = 0 WHERE id = ?", (produto_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok", "msg": "Produto desativado com sucesso!"})
    except Exception as e:
        conn.close()
        return jsonify({
            "status": "error",
            "msg": f"Erro ao desativar produto: {e}"
        })

@app.route("/ajax_add_produto_id", methods=["POST"])
@login_required
def ajax_add_produto_id():
    data = request.get_json() or {}
    produto_id = int(data.get("produto_id") or 0)
    quantidade = int(data.get("quantidade") or 1)

    if not produto_id or quantidade < 1:
        return jsonify({"status": "error", "msg": "Dados inválidos."})

    conn = get_db_connection()
    produto = conn.execute(
    "SELECT id, nome, preco, estoque FROM produtos WHERE ativo = 1 AND id=?",
    (produto_id,)
    ).fetchone()

    if not produto:
        conn.close()
        return jsonify({"status": "error", "msg": "Produto não encontrado."})
    if produto["estoque"] < quantidade:
        conn.close()
        return jsonify({"status": "error", "msg": f"Estoque insuficiente. Disponível: {produto['estoque']}."})

    usuario = session.get("username", "Desconhecido")
    conn.execute("""
        INSERT INTO pedidos (produto_id, quantidade, status, usuario)
        VALUES (?, ?, 'aberta', ?)
    """, (produto_id, quantidade, usuario))
    conn.execute("UPDATE produtos SET estoque = estoque - ? WHERE id = ?", (quantidade, produto_id))
    conn.commit()
    ped_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()

    return jsonify({
        "status": "ok",
        "pedido": {"id": ped_id, "quantidade": quantidade},
        "produto": {"nome": produto["nome"], "preco": produto["preco"]}
    })

# Importar produtos via CSV
# -------------------------
@app.route("/produtos/importar", methods=["POST"])
@login_required
def importar_produtos_csv():
    file = request.files.get("file")
    if not file:
        flash("Nenhum arquivo enviado.", "warning")
        return redirect(url_for("produtos_page"))

    try:
        try:
            # tenta UTF-8 primeiro
            raw_data = file.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            # Excel no Windows usa Latin-1 (Windows-1252)
            file.stream.seek(0)
            raw_data = file.stream.read().decode("latin-1")

        # 🔹 detecta separador automático
        sep = ";" if raw_data.count(";") > raw_data.count(",") else ","
        stream = StringIO(raw_data)

        linhas = stream.readlines()
        conn = get_db_connection()
        count_new, count_update, count_error = 0, 0, 0

        # pula cabeçalho
        header = [x.strip() for x in linhas[0].replace("\n", "").split(sep)]
        for i, line in enumerate(linhas[1:], start=2):
            try:
                cols = [x.strip() for x in line.replace("\n", "").split(sep)]
                if len(cols) < 4:
                    count_error += 1
                    continue

                data = dict(zip(header, cols))
                codigo = data.get("codigo_barra", "")
                nome = data.get("nome", "")
                preco_raw = data.get("preco", "").replace("R$", "").replace(",", ".").strip()
                estoque_raw = data.get("estoque", "").strip()
                categoria = data.get("categoria", "Outros").strip()

                if not nome:
                    continue

                preco = float(preco_raw or 0)
                estoque = int(float(estoque_raw or 0))

                existente = conn.execute("""
                    SELECT id FROM produtos WHERE codigo_barra=?
                """, (codigo,)).fetchone()

                if existente:
                    conn.execute("""
                        UPDATE produtos 
                        SET nome=?, preco=?, estoque=?, ativo=1, categoria=?
                        WHERE codigo_barra=?
                    """, (nome, preco, estoque, categoria, codigo))
                    count_update += 1
                else:
                    conn.execute("""
                        INSERT INTO produtos (codigo_barra, nome, preco, estoque, ativo, categoria)
                        VALUES (?, ?, ?, ?, 1, ?)
                    """, (codigo, nome, preco, estoque, categoria))
                    count_new += 1



            except Exception as e:
                count_error += 1
                print(f"⚠️ Linha {i} com erro: {e}")

        conn.commit()
        conn.close()

        flash(f"✅ Importação concluída: {count_new} novos, {count_update} atualizados, {count_error} com erro(s).", "success")

    except Exception as e:
        flash(f"Erro ao importar: {e}", "danger")

    return redirect(url_for("produtos_page"))



# -------------------------
# Exportar produtos para CSV
# -------------------------
@app.route("/produtos/exportar")
@login_required
def exportar_produtos_csv():
    conn = get_db_connection()
    # 🔹 Busca todos os produtos sem limite
    produtos = conn.execute("SELECT codigo_barra, nome, preco, estoque, categoria FROM produtos ORDER BY nome COLLATE NOCASE").fetchall()
    conn.close()

    if not produtos:
        flash("Nenhum produto encontrado para exportar.", "info")
        return redirect(url_for("produtos_page"))

    # 🔹 Gera CSV com separador ';' e vírgula como decimal
    si = StringIO()
    writer = csv.writer(si, delimiter=';')
    writer.writerow(["codigo_barra", "nome", "preco", "estoque", "categoria"])
    for p in produtos:
        preco_str = f"{p['preco']:.2f}".replace('.', ',')  # converte ponto em vírgula
        writer.writerow([p['codigo_barra'], p['nome'], preco_str, p['estoque'], p['categoria']])

    si.seek(0)

    # 🔹 Força o download completo
    return send_file(
        BytesIO(si.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"produtos_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv"
    )

@app.route("/vendas")
@login_required
def vendas():
    conn = get_db_connection()
    usuario = session.get("username", "Desconhecido")
    role = session.get("role", "attendant")

    # 🔹 Produtos disponíveis
    produtos = conn.execute(
    "SELECT * FROM produtos WHERE ativo = 1 AND estoque > 0"
    ).fetchall()

    # 🔹 Pedidos abertos SOMENTE do usuário logado
    pedidos = conn.execute("""
        SELECT ped.id, pr.nome, pr.preco, ped.quantidade, 
               (pr.preco * ped.quantidade) AS total
        FROM pedidos ped
        JOIN produtos pr ON ped.produto_id = pr.id
        WHERE ped.status = 'aberta' AND ped.usuario = ?
        ORDER BY ped.id DESC                   
    """, (usuario,)).fetchall()

    total_geral = sum(p["total"] for p in pedidos)

    # 🔹 Histórico de vendas — admin vê todos, atendente vê só as próprias
    if role == "admin":
        historico = conn.execute("""
            SELECT id, data_hora, total, desconto, recebido, troco, forma_pagamento, usuario
            FROM caixa
            ORDER BY id DESC
            LIMIT 5
        """).fetchall()
    else:
        historico = conn.execute("""
            SELECT id, data_hora, total, desconto, recebido, troco, forma_pagamento, usuario
            FROM caixa
            WHERE usuario = ?
            ORDER BY id DESC
            LIMIT 10
        """, (usuario,)).fetchall()

    conn.close()

    return render_template(
        "vendas.html",
        produtos=produtos,
        pedidos=pedidos,
        total_geral=total_geral,
        historico=historico,
        commerce=get_setting("commerce_name", "ROYAL BEBIDAS")
    )

@app.route("/ajax_reabrir_venda/<int:venda_id>", methods=["POST"])
@login_required
def ajax_reabrir_venda(venda_id):
    conn = get_db_connection()
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    usuario_logado = session.get("username", "Desconhecido")
    role = session.get("role", "attendant")

    venda = cur.execute("""
        SELECT id, usuario FROM caixa WHERE id = ?
    """, (venda_id,)).fetchone()

    if not venda:
        conn.close()
        return jsonify({"status": "error", "msg": "❌ Venda não encontrada."})

    if venda["usuario"] != usuario_logado and role != "admin":
        conn.close()
        return jsonify({
            "status": "error",
            "msg": f"⚠️ Esta venda pertence ao operador '{venda['usuario']}'."
        })

    itens = cur.execute("""
        SELECT produto_id, produto_nome, quantidade, preco_unitario
        FROM venda_itens WHERE venda_id = ?
    """, (venda_id,)).fetchall()

    if not itens:
        conn.close()
        return jsonify({"status": "error", "msg": "⚠️ Nenhum item encontrado."})

    try:
        # Deleta tabelas filhas antes da principal
        cur.execute("DELETE FROM venda_itens WHERE venda_id = ?", (venda_id,))
        cur.execute("DELETE FROM pagamentos WHERE venda_id = ?", (venda_id,))
        cur.execute("DELETE FROM caixa WHERE id = ?", (venda_id,))

        # Limpa pedidos abertos
        cur.execute("DELETE FROM pedidos WHERE status='aberta' AND usuario=?", (usuario_logado,))

        # Reabre itens da venda
        for item in itens:
            cur.execute("""
                INSERT INTO pedidos (produto_id, quantidade, status, usuario)
                VALUES (?, ?, 'aberta', ?)
            """, (item["produto_id"], item["quantidade"], usuario_logado))

        conn.commit()
        return jsonify({
            "status": "ok",
            "msg": f"✅ Venda #{venda_id} reaberta com sucesso pelo operador {usuario_logado}."
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "msg": f"Erro ao reabrir venda: {e}"})
    finally:
        conn.close()




# -------------------------
# AJAX Routes (PDV)
# -------------------------
@app.route("/autocomplete_produto")
@login_required
def autocomplete_produto():
    q = request.args.get("q","").strip()
    conn = get_db_connection()
    produtos = conn.execute("SELECT id, nome, preco, estoque FROM produtos WHERE ativo = 1 AND (nome LIKE ? OR codigo_barra LIKE ?)LIMIT 10",
                            (f"%{q}%", f"%{q}%")).fetchall()
    conn.close()
    results = [{"id": p["id"], "nome": p["nome"], "preco": p["preco"], "estoque": p["estoque"]} for p in produtos]
    return jsonify(results)

@app.route("/ajax_add_produto", methods=["POST"])
@login_required
def ajax_add_produto():
    """Adiciona produto à venda pelo nome OU código de barras (vinculado ao operador logado)."""
    data = request.get_json() or {}
    termo = data.get("nome", "").strip()
    quantidade = int(data.get("quantidade") or 1)

    if not termo or quantidade < 1:
        return jsonify({"status": "error", "msg": "Dados inválidos: produto ou quantidade."})

    conn = get_db_connection()

    import re
    codigo_limpo = re.sub(r"[^0-9A-Za-z]", "", termo)

    # 🔹 Busca o produto pelo código exato ou nome parcial
    produto = conn.execute("""
        SELECT * FROM produtos
        WHERE ativo = 1
        AND (codigo_barra = ? COLLATE NOCASE
            OR nome LIKE ? COLLATE NOCASE)
        LIMIT 1
    """, (codigo_limpo, f"%{termo}%")).fetchone()


    if not produto:
        conn.close()
        return jsonify({
            "status": "error",
            "msg": f"Produto '{termo}' não encontrado."
        })

    # 🔹 Valida estoque
    if produto["estoque"] < quantidade:
        conn.close()
        return jsonify({
            "status": "error",
            "msg": f"Estoque insuficiente. Disponível: {produto['estoque']}."
        })

    # 🔹 Pega o usuário logado
    usuario = session.get("username", "Desconhecido")

    # 🔹 Registra o pedido vinculado ao operador logado
    conn.execute("""
        INSERT INTO pedidos (produto_id, quantidade, status, usuario)
        VALUES (?, ?, 'aberta', ?)
    """, (produto["id"], quantidade, usuario))

    # 🔹 Atualiza estoque
    conn.execute("UPDATE produtos SET estoque = estoque - ? WHERE id = ?", (quantidade, produto["id"]))

    conn.commit()
    ped_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()

    return jsonify({
        "status": "ok",
        "pedido": {"id": ped_id, "quantidade": quantidade},
        "produto": {"nome": produto["nome"], "preco": produto["preco"]},
        "msg": f"✅ {quantidade}x '{produto['nome']}' adicionado com sucesso!"
    })



# -------------------------
# NOVO: Cancelar item (devolve estoque e registra)
# -------------------------
@app.route("/ajax_cancelar_item/<int:pedido_id>", methods=["POST"])
@login_required
def ajax_cancelar_item(pedido_id):
    conn = get_db_connection()
    item = conn.execute("""
        SELECT ped.produto_id, ped.quantidade, pr.nome, pr.preco
        FROM pedidos ped
        JOIN produtos pr ON pr.id = ped.produto_id
        WHERE ped.id=? AND ped.status='aberta'
    """, (pedido_id,)).fetchone()
    if not item:
        conn.close()
        return jsonify({"status":"error","msg":"Item não encontrado ou já fechado."})

    conn.execute("UPDATE produtos SET estoque=estoque+? WHERE id=?", (item["quantidade"], item["produto_id"]))
    conn.execute("""
        INSERT INTO cancelamentos (produto_id, nome, quantidade, preco_unitario, usuario)
        VALUES (?,?,?,?,?)
    """, (item["produto_id"], item["nome"], item["quantidade"], item["preco"], session.get("username","desconhecido")))
    conn.execute("DELETE FROM pedidos WHERE id=?", (pedido_id,))
    conn.commit()
    conn.close()
    return jsonify({"status":"ok","msg":f"Produto '{item['nome']}' cancelado e estoque devolvido."})

# =========================================================
# 🔹 FECHAR VENDA (PDV simples)
# =========================================================
@app.route("/ajax_fechar_venda", methods=["POST"])
@login_required
def ajax_fechar_venda():
    data = request.get_json() or {}
    desconto = float(data.get("desconto", 0))
    total_final = float(data.get("total_final", 0))
    pagamentos = data.get("pagamentos", [])
    total_recebido = float(data.get("total_recebido", 0))
    troco = float(data.get("troco", 0))

    conn = get_db_connection()
    cur = conn.cursor()

    # 🔒 Garante tabelas necessárias
    cur.execute("""
    CREATE TABLE IF NOT EXISTS venda_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id INTEGER,
        produto_id INTEGER,
        produto_nome TEXT,
        quantidade INTEGER,
        preco_unitario REAL,
        usuario TEXT,
        data_hora TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (venda_id) REFERENCES caixa(id) ON DELETE CASCADE,
        FOREIGN KEY (produto_id) REFERENCES produtos(id)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pagamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id INTEGER,
        comanda_id INTEGER,
        forma_pagamento TEXT,
        valor REAL,
        data_hora TEXT DEFAULT (datetime('now','localtime'))
    )
    """)

    usuario = session.get("username", "Desconhecido")

    # 🔹 Itens do operador logado
    itens = cur.execute("""
        SELECT ped.id, p.id AS produto_id, p.nome, p.preco, ped.quantidade
        FROM pedidos ped
        JOIN produtos p ON ped.produto_id = p.id
        WHERE ped.status = 'aberta' AND ped.usuario = ?
    """, (usuario,)).fetchall()

    if not itens:
        conn.close()
        return jsonify({"status": "error", "msg": "Nenhum produto adicionado à venda."})

    # 🔹 Dados de fechamento
    forma_principal = pagamentos[0]["forma_pagamento"] if len(pagamentos) == 1 else "Múltipla"
    recebido_total = total_recebido or sum(p["valor"] for p in pagamentos)
    troco = troco or max(recebido_total - total_final, 0)


    # 🔹 Registra a venda no caixa
    cur.execute("""
        INSERT INTO caixa (data_hora, total, desconto, recebido, troco, forma_pagamento, usuario)
        VALUES (datetime('now','localtime'), ?, ?, ?, ?, ?, ?)
    """, (total_final, desconto, recebido_total, troco, forma_principal, usuario))
    venda_id = cur.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    # 🔹 Registra os itens vendidos
    for i in itens:
        cur.execute("""
            INSERT INTO venda_itens (venda_id, produto_id, produto_nome, quantidade, preco_unitario, usuario)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (venda_id, i["produto_id"], i["nome"], i["quantidade"], i["preco"], usuario))

    # 🔹 Registra os pagamentos individuais
    for p in pagamentos:
        cur.execute("""
            INSERT INTO pagamentos (venda_id, forma_pagamento, valor)
            VALUES (?, ?, ?)
        """, (venda_id, p["forma_pagamento"], p["valor"]))

    # 🔹 Limpa pedidos abertos do operador
    cur.execute("DELETE FROM pedidos WHERE status = 'aberta' AND usuario = ?", (usuario,))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "msg": f"✅ Venda finalizada! Total R$ {total_final:.2f} | Recebido R$ {recebido_total:.2f} | Troco R$ {troco:.2f}"
    })







# -------------------------
# Página de Cancelamentos
# -------------------------
@app.route("/cancelamentos")
@login_required
def cancelamentos_page():
    conn = get_db_connection()
    registros = conn.execute("""
        SELECT nome, quantidade, preco_unitario, usuario, data_hora
        FROM cancelamentos ORDER BY data_hora DESC
    """).fetchall()
    conn.close()
    return render_template("cancelamentos.html", cancelamentos=registros,
                           commerce=get_setting("commerce_name", "ROYAL BEBIDAS"))
@app.route("/exportar_cancelamentos_excel")
@login_required
def exportar_cancelamentos_excel():
    """Exporta a tabela de cancelamentos para um arquivo Excel (.xlsx)."""
    conn = get_db_connection()
    df = pd.read_sql_query("""
        SELECT id AS 'ID',
               data_hora AS 'Data/Hora',
               nome AS 'Produto',
               quantidade AS 'Quantidade',
               preco_unitario AS 'Preço Unitário (R$)',
               (quantidade * preco_unitario) AS 'Total (R$)',
               usuario AS 'Usuário'
        FROM cancelamentos
        ORDER BY data_hora DESC
    """, conn)
    conn.close()

    if df.empty:
        flash("Nenhum cancelamento encontrado para exportar.", "info")
        return redirect(url_for("cancelamentos_page"))

    # Gera o arquivo Excel em memória
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Cancelamentos")
    output.seek(0)

    nome_arquivo = f"cancelamentos_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# -------------------------
# Comandas
# -------------------------
@app.route("/comandas")
@login_required
def comandas_page():
    conn = get_db_connection()
    # Busca todas as comandas existentes
    comandas = conn.execute("""
    SELECT id, numero, cliente, observacao, status, 
           COALESCE(total, 0) AS total,
           usuario
    FROM comandas
    ORDER BY id DESC
""").fetchall()

    # Busca produtos disponíveis para adicionar
    produtos = conn.execute(
    "SELECT id, nome, preco FROM produtos WHERE ativo = 1 AND estoque > 0"
    ).fetchall()

    conn.close()
    return render_template(
        "comandas.html",
        comandas=comandas,
        produtos=produtos,
        commerce=get_setting("commerce_name", "ROYAL BEBIDAS")
    )
# -------------------------
# Gerar próximo número de comanda automaticamente
# -------------------------
@app.route("/ajax_proximo_numero_comanda")
@login_required
def ajax_proximo_numero_comanda():
    conn = get_db_connection()
    ultimo = conn.execute("SELECT MAX(CAST(numero AS INTEGER)) FROM comandas").fetchone()[0]
    proximo = (int(ultimo) + 1) if ultimo else 1
    conn.close()
    return jsonify({"proximo": proximo})

# -------------------------
# Adicionar nova comanda
# -------------------------
@app.route("/ajax_nova_comanda", methods=["POST"])
@login_required
def ajax_nova_comanda():
    data = request.get_json()
    numero = data.get("numero", "").strip()
    cliente = data.get("cliente", "").strip()
    observacao = data.get("observacao", "").strip()

    if not numero:
        return jsonify({"status": "error", "msg": "Número da comanda é obrigatório."})

    conn = get_db_connection()
    existente = conn.execute("SELECT id FROM comandas WHERE numero=?", (numero,)).fetchone()
    if existente:
        conn.close()
        return jsonify({"status": "error", "msg": "Já existe uma comanda com este número."})

    usuario = session.get("username", "Desconhecido")

    conn.execute("""
        INSERT INTO comandas (numero, cliente, observacao, total, status, usuario)
        VALUES (?, ?, ?, 0, 'aberta', ?)
    """, (numero, cliente, observacao, usuario))


    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "msg": "Comanda criada com sucesso!"})


# -------------------------
# Adicionar item à comanda
# -------------------------
# -------------------------
# Adicionar item à comanda
# -------------------------
@app.route("/ajax_add_item_comanda", methods=["POST"])
@login_required
def ajax_add_item_comanda():
    data = request.get_json()
    comanda_id = data.get("comanda_id")
    produto_id = data.get("produto_id")
    quantidade = int(data.get("quantidade", 1))

    conn = get_db_connection()
    produto = conn.execute(
    "SELECT nome, preco, estoque FROM produtos WHERE ativo = 1 AND id=?",
    (produto_id,)
    ).fetchone()

    if not produto:
        conn.close()
        return jsonify({"status": "error", "msg": "Produto não encontrado."})
    if produto["estoque"] < quantidade:
        conn.close()
        return jsonify({"status": "error", "msg": f"Estoque insuficiente. Disponível: {produto['estoque']}."})

    # 🔹 Insere item na comanda
    conn.execute("""
        INSERT INTO comanda_itens (comanda_id, produto_id, quantidade, preco_unitario)
        VALUES (?, ?, ?, ?)
    """, (comanda_id, produto_id, quantidade, produto["preco"]))

    # 🔹 Atualiza estoque do produto
    conn.execute("UPDATE produtos SET estoque = estoque - ? WHERE id = ?", (quantidade, produto_id))

    # 🔹 Recalcula total da comanda
    total = conn.execute("""
        SELECT COALESCE(SUM(quantidade * preco_unitario), 0) AS total
        FROM comanda_itens
        WHERE comanda_id = ?
    """, (comanda_id,)).fetchone()["total"]

    conn.execute("UPDATE comandas SET total = ? WHERE id = ?", (total, comanda_id))
    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "msg": f"✅ {quantidade}x '{produto['nome']}' adicionado à comanda.",
        "total": float(total)
    })


# 🔸 Adicionar item à comanda via código de barras
@app.route("/ajax_add_item_comanda_codigo", methods=["POST"])
@login_required
def ajax_add_item_comanda_codigo():
    data = request.get_json()
    comanda_id = data.get("comanda_id")
    codigo = data.get("codigo", "").strip()
    quantidade = int(data.get("quantidade") or 1)  # ✅ agora lê a quantidade enviada do front-end

    import re
    codigo_limpo = re.sub(r"[^0-9]", "", codigo)
    conn = get_db_connection()
    produto = conn.execute(
        "SELECT id, nome, preco, estoque FROM produtos WHERE ativo = 1 AND codigo_barra LIKE ? LIMIT 1",
        (f"%{codigo_limpo}%",)
    ).fetchone()

    if not produto:
        conn.close()
        return jsonify({"status": "error", "msg": f"Produto '{codigo}' não encontrado."})

    if produto["estoque"] < quantidade:
        conn.close()
        return jsonify({
            "status": "error",
            "msg": f"Estoque insuficiente. Disponível: {produto['estoque']}."
        })

    # 🔹 Insere o item com a quantidade correta
    conn.execute(
        "INSERT INTO comanda_itens (comanda_id, produto_id, quantidade, preco_unitario) VALUES (?, ?, ?, ?)",
        (comanda_id, produto["id"], quantidade, produto["preco"])
    )

    # 🔹 Atualiza o estoque
    conn.execute("UPDATE produtos SET estoque = estoque - ? WHERE id = ?", (quantidade, produto["id"]))
    conn.commit()

    # 🔹 Recalcula o total da comanda
    total = conn.execute(
        "SELECT SUM(quantidade * preco_unitario) FROM comanda_itens WHERE comanda_id=?",
        (comanda_id,)
    ).fetchone()[0] or 0
    conn.execute("UPDATE comandas SET total=? WHERE id=?", (total, comanda_id))
    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "msg": f"✅ {quantidade}x '{produto['nome']}' adicionado à comanda."
    })


# 🔸 Adicionar item à comanda via nome
@app.route("/ajax_add_item_comanda_nome", methods=["POST"])
@login_required
def ajax_add_item_comanda_nome():
    data = request.get_json()
    comanda_id = data.get("comanda_id")
    nome = data.get("nome", "").strip()
    quantidade = int(data.get("quantidade", 1))

    conn = get_db_connection()
    produto = conn.execute(
        "SELECT id, nome, preco, estoque FROM produtos WHERE ativo = 1 AND (nome LIKE ? OR codigo_barra LIKE ?) LIMIT 1",
        (f"%{nome}%", f"%{nome}%")
    ).fetchone()

    if not produto:
        conn.close()
        return jsonify({"status": "error", "msg": f"Produto '{nome}' não encontrado."})
    if produto["estoque"] < quantidade:
        conn.close()
        return jsonify({"status": "error", "msg": f"Estoque insuficiente. Disponível: {produto['estoque']}."})

    conn.execute(
        "INSERT INTO comanda_itens (comanda_id, produto_id, quantidade, preco_unitario) VALUES (?, ?, ?, ?)",
        (comanda_id, produto["id"], quantidade, produto["preco"])
    )
    conn.execute("UPDATE produtos SET estoque = estoque - ? WHERE id = ?", (quantidade, produto["id"]))
    conn.commit()
    # 🔹 Atualiza o total da comanda
    # 🔹 Recalcula o total da comanda
    total = conn.execute("""
        SELECT COALESCE(SUM(quantidade * preco_unitario), 0) AS total
        FROM comanda_itens
        WHERE comanda_id = ?
    """, (comanda_id,)).fetchone()["total"]

    conn.execute("UPDATE comandas SET total=? WHERE id=?", (total, comanda_id))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "msg": "Item adicionado à comanda com sucesso!", "total": float(total)})

# -------------------------
# Listar itens da comanda
# -------------------------
@app.route("/ajax_listar_itens_comanda/<int:comanda_id>", methods=["GET"])
@login_required
def ajax_listar_itens_comanda(comanda_id):
    conn = get_db_connection()
    itens = conn.execute("""
        SELECT ci.id, pr.nome, ci.quantidade, ci.preco_unitario,
               (ci.quantidade * ci.preco_unitario) AS subtotal
        FROM comanda_itens ci
        JOIN produtos pr ON pr.id = ci.produto_id
        WHERE ci.comanda_id = ?
    """, (comanda_id,)).fetchall()

    total = conn.execute("""
        SELECT COALESCE(SUM(quantidade * preco_unitario), 0) AS total
        FROM comanda_itens
        WHERE comanda_id=?
    """, (comanda_id,)).fetchone()["total"]

    # 🔹 Atualiza o campo total da comanda (para manter sincronizado)
    conn.execute("UPDATE comandas SET total=? WHERE id=?", (total, comanda_id))
    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "itens": [dict(i) for i in itens],
        "total": float(total or 0)
    })

# -------------------------
# Cancelar item da comanda (com registro)
# -------------------------
@app.route("/ajax_cancelar_item_comanda/<int:item_id>", methods=["POST"])
@login_required
def ajax_cancelar_item_comanda(item_id):
    conn = get_db_connection()
    item = conn.execute("""
        SELECT ci.id, ci.comanda_id, ci.produto_id, ci.quantidade,
               pr.nome, pr.preco
        FROM comanda_itens ci
        JOIN produtos pr ON pr.id = ci.produto_id
        WHERE ci.id=?
    """, (item_id,)).fetchone()

    if not item:
        conn.close()
        return jsonify({"status":"error","msg":"Item não encontrado."})

    # devolve estoque
    conn.execute("UPDATE produtos SET estoque = estoque + ? WHERE id = ?", (item["quantidade"], item["produto_id"]))

    # registra cancelamento
    conn.execute("""
        INSERT INTO cancelamentos (produto_id, nome, quantidade, preco_unitario, usuario)
        VALUES (?, ?, ?, ?, ?)
    """, (item["produto_id"], item["nome"], item["quantidade"], item["preco"], session.get("username","desconhecido")))

    # remove item da comanda
    conn.execute("DELETE FROM comanda_itens WHERE id=?", (item_id,))
    conn.commit()

    # atualiza total da comanda
    total = conn.execute("SELECT SUM(quantidade * preco_unitario) AS total FROM comanda_itens WHERE comanda_id=?",
                         (item["comanda_id"],)).fetchone()["total"] or 0
    conn.execute("UPDATE comandas SET total=? WHERE id=?", (total, item["comanda_id"]))
    conn.commit()
    conn.close()

    return jsonify({"status":"ok", "msg":f"Item '{item['nome']}' cancelado e estoque devolvido."})

# -------------------------
# Fechar comanda
# -------------------------
@app.route("/ajax_fechar_comanda/<int:comanda_id>", methods=["POST"])
@login_required
def ajax_fechar_comanda(comanda_id):
    data = request.get_json() or {}
    desconto = float(data.get("desconto", 0))
    recebido = float(data.get("recebido", 0))
    forma_pagamento = data.get("forma_pagamento", "Dinheiro")

    conn = get_db_connection()

    # 🔹 Calcula o total diretamente dos itens
    total_itens = conn.execute("""
        SELECT COALESCE(SUM(quantidade * preco_unitario), 0) AS total
        FROM comanda_itens
        WHERE comanda_id = ?
    """, (comanda_id,)).fetchone()["total"]

    comanda = conn.execute("SELECT numero, cliente FROM comandas WHERE id=?", (comanda_id,)).fetchone()
    if not comanda:
        conn.close()
        return jsonify({"status": "error", "msg": "Comanda não encontrada."})

    total_final = max(total_itens - desconto, 0)
    troco = max(recebido - total_final, 0)

    conn.execute("""
        UPDATE comandas
        SET status='fechada', desconto=?, recebido=?, troco=?, total=?
        WHERE id=?
    """, (desconto, recebido, troco, total_final, comanda_id))

    usuario = session.get("username", "Desconhecido")

    conn.execute("""
        INSERT INTO caixa (data_hora, total, desconto, recebido, troco, forma_pagamento, usuario)
        VALUES (datetime('now','localtime'), ?, ?, ?, ?, ?, ?)
    """, (total_final, desconto, recebido, troco, forma_pagamento, usuario))


    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "msg": f"✅ Comanda {comanda['numero']} fechada! "
               f"Total: R$ {total_final:.2f} | Pagamento: {forma_pagamento} | Troco: R$ {troco:.2f}"
    })
@app.route("/ajax_reabrir_comanda/<int:comanda_id>", methods=["POST"])
@login_required
def ajax_reabrir_comanda(comanda_id):
    conn = get_db_connection()
    cur = conn.cursor()

    usuario_logado = session.get("username", "Desconhecido")
    role = session.get("role", "attendant")

    # 🔹 Verifica se a comanda existe
    comanda = cur.execute("""
        SELECT id, numero, cliente, status, usuario
        FROM comandas
        WHERE id = ?
    """, (comanda_id,)).fetchone()

    if not comanda:
        conn.close()
        return jsonify({"status": "error", "msg": "❌ Comanda não encontrada."})

    # 🔒 Impede reabrir comandas já abertas
    if comanda["status"] == "aberta":
        conn.close()
        return jsonify({"status": "error", "msg": f"⚠️ A comanda #{comanda['numero']} já está aberta."})

    # 🔐 Permite apenas o mesmo operador OU um admin
    if comanda["usuario"] != usuario_logado and role != "admin":
        conn.close()
        return jsonify({
            "status": "error",
            "msg": f"⚠️ Esta comanda pertence ao operador '{comanda['usuario']}'. Você não tem permissão para reabrir."
        })

    # 🔹 Atualiza status e zera valores de fechamento
    cur.execute("""
        UPDATE comandas
        SET status = 'aberta', desconto = 0, recebido = 0, troco = 0
        WHERE id = ?
    """, (comanda_id,))

    # 🔹 Remove apenas o registro do caixa referente a esta comanda
    cur.execute("""
        DELETE FROM caixa
        WHERE total = (SELECT total FROM comandas WHERE id = ?)
          AND usuario = (SELECT usuario FROM comandas WHERE id = ?)
          AND ABS(strftime('%s','now') - strftime('%s', data_hora)) < 86400
    """, (comanda_id, comanda_id))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "msg": f"✅ Comanda #{comanda['numero']} reaberta com sucesso!"
    })



# -------------------------
# Relatório Mensal
# -------------------------
from datetime import datetime

@app.route("/relatorio_mensal")
@login_required
def relatorio_mensal():
    mes = request.args.get("mes") or datetime.now().strftime("%Y-%m")
    ano, mes_num = mes.split("-")

    conn = get_db_connection()
    dados = conn.execute("""
        SELECT 
            COUNT(*) AS qtd_vendas,
            SUM(total) AS total_vendas,
            SUM(desconto) AS total_desconto,
            SUM(troco) AS total_troco
        FROM caixa
        WHERE strftime('%Y-%m', data_hora) = ?
    """, (mes,)).fetchone()
    conn.close()

    return render_template(
        "relatorio_mensal.html",
        mes=mes,
        dados=dados,
        commerce=get_setting("commerce_name", "ROYAL BEBIDAS")
    )

# -------------------------
# Relatório Anual
# -------------------------
@app.route("/relatorio_anual")
@login_required
def relatorio_anual():
    ano = request.args.get("ano") or datetime.now().strftime("%Y")

    conn = get_db_connection()
    meses = conn.execute("""
        SELECT 
            strftime('%m', data_hora) AS mes,
            SUM(total) AS total_vendas
        FROM caixa
        WHERE strftime('%Y', data_hora) = ?
        GROUP BY mes
        ORDER BY mes
    """, (ano,)).fetchall()
    conn.close()

    # Monta os dados para gráfico
    labels = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
    valores = [0]*12
    for m in meses:
        idx = int(m["mes"]) - 1
        valores[idx] = float(m["total_vendas"] or 0)

    return render_template(
        "relatorio_anual.html",
        ano=ano,
        labels=labels,
        valores=valores,
        meses=meses,
        commerce=get_setting("commerce_name","ROYAL BEBIDAS")
    )
# -------------------------
# Relatório Financeiro (Filtro)
# -------------------------
@app.route("/relatorio", methods=["GET"])
@login_required
def relatorio():
    """Relatório filtrável por dia, mês ou ano + forma de pagamento."""
    filtro = request.args.get("filtro", "dia")
    valor = request.args.get("valor", datetime.now().strftime("%Y-%m-%d"))

    conn = get_db_connection()
    query_base = """
        SELECT data_hora, total, desconto, recebido, troco, forma_pagamento
        FROM caixa
        WHERE 1=1
    """
    params = []

    # 🔹 Filtro de período
    if filtro == "dia":
        query_base += " AND DATE(data_hora) = ?"
        params.append(valor)
    elif filtro == "mes":
        query_base += " AND strftime('%Y-%m', data_hora) = ?"
        params.append(valor)
    elif filtro == "ano":
        query_base += " AND strftime('%Y', data_hora) = ?"
        params.append(valor)

    dados = conn.execute(query_base + " ORDER BY data_hora DESC", params).fetchall()

    # 🔹 Totais agregados
    totais = conn.execute(f"""
        SELECT COUNT(*) AS qtd,
               SUM(total) AS soma_total,
               SUM(desconto) AS soma_desc,
               SUM(recebido) AS soma_recebido,
               SUM(troco) AS soma_troco
        FROM ({query_base})
    """, params).fetchone()

    # 🔹 Totais por forma de pagamento
    por_pagamento = conn.execute(f"""
        SELECT forma_pagamento, SUM(total) AS total
        FROM ({query_base})
        GROUP BY forma_pagamento
    """, params).fetchall()
    conn.close()

    return render_template(
        "relatorio_filtro.html",
        filtro=filtro,
        valor=valor,
        dados=dados,
        totais=totais,
        por_pagamento=por_pagamento,
        commerce=get_setting("commerce_name", "ROYAL BEBIDAS")
    )

# -------------------------
# Exportar Relatório para Excel
# -------------------------
@app.route("/relatorio/exportar_excel")
@login_required
def exportar_excel():
    """Exporta o relatório atual filtrado para Excel (.xlsx)."""
    filtro = request.args.get("filtro", "dia")
    valor = request.args.get("valor", datetime.now().strftime("%Y-%m-%d"))

    conn = get_db_connection()
    query_base = """
        SELECT data_hora AS 'Data/Hora',
               total AS 'Total (R$)',
               desconto AS 'Desconto (R$)',
               recebido AS 'Recebido (R$)',
               troco AS 'Troco (R$)',
               forma_pagamento AS 'Forma de Pagamento'
        FROM caixa
        WHERE 1=1
    """
    params = []

    # 🔹 Filtro aplicado
    if filtro == "dia":
        query_base += " AND DATE(data_hora) = ?"
        params.append(valor)
    elif filtro == "mes":
        query_base += " AND strftime('%Y-%m', data_hora) = ?"
        params.append(valor)
    elif filtro == "ano":
        query_base += " AND strftime('%Y', data_hora) = ?"
        params.append(valor)

    df = pd.read_sql_query(query_base + " ORDER BY data_hora DESC", conn, params=params)
    conn.close()

    if df.empty:
        return jsonify({"status": "error", "msg": "Nenhum dado encontrado para exportar."})

    # 🔸 Cria Excel em memória
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Relatório")
    output.seek(0)

    nome = f"relatorio_{filtro}_{valor}.xlsx".replace(":", "-")
    return send_file(
        output,
        as_attachment=True,
        download_name=nome,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
@app.route("/fechamento_caixa")
@login_required
def fechamento_caixa_page():
    conn = get_db_connection()
    usuario_logado = session.get("username", "Desconhecido")
    role = session.get("role", "attendant")

    # 🔹 Último fechamento do operador logado
    ultimo = conn.execute("""
        SELECT data_hora, usuario, total_liquido
        FROM fechamentos
        WHERE usuario = ?
        ORDER BY id DESC LIMIT 1
    """, (usuario_logado,)).fetchone()

    # 🔹 Totais do dia (por operador)
    dados = conn.execute("""
        SELECT 
            COUNT(*) AS qtd_vendas,
            SUM(total) AS total_vendas,
            SUM(desconto) AS total_descontos,
            SUM(recebido) AS total_recebido,
            SUM(troco) AS total_troco
        FROM caixa
        WHERE DATE(data_hora) = DATE('now','localtime')
          AND usuario = ?
    """, (usuario_logado,)).fetchone()

    # 🔹 Resumo por forma de pagamento
    por_pagamento = conn.execute("""
        SELECT 
            forma_pagamento,
            SUM(total) AS total_vendas,
            SUM(desconto) AS total_descontos,
            SUM(
                CASE 
                    WHEN forma_pagamento = 'Dinheiro' THEN (recebido - troco)
                    ELSE recebido
                END
            ) AS total_liquido
        FROM caixa
        WHERE DATE(data_hora) = DATE('now','localtime')
          AND usuario = ?
        GROUP BY forma_pagamento
    """, (usuario_logado,)).fetchall()

    por_pagamento_json = json.dumps([dict(row) for row in por_pagamento])

    # 🔹 Histórico (admin vê todos / atendente só o dele)
    filtro_data = request.args.get("data") or datetime.now().strftime("%Y-%m-%d")
    if role == "admin":
        historico = conn.execute("""
            SELECT id, data_hora, usuario, turno, total_liquido, observacao
            FROM fechamentos
            WHERE DATE(data_hora) = ?
            ORDER BY id DESC
        """, (filtro_data,)).fetchall()
    else:
        historico = conn.execute("""
            SELECT id, data_hora, usuario, turno, total_liquido, observacao
            FROM fechamentos
            WHERE DATE(data_hora) = ? AND usuario = ?
            ORDER BY id DESC
        """, (filtro_data, usuario_logado)).fetchall()

    conn.close()

    return render_template(
        "fechamento_caixa.html",
        dados=dados,
        por_pagamento=por_pagamento,
        por_pagamento_json=por_pagamento_json,
        historico=historico,
        ultimo=ultimo,
        filtro_data=filtro_data,
        commerce=get_setting("commerce_name", "ROYAL BEBIDAS"),
    )



@app.route("/ajax_fechar_caixa", methods=["POST"])
@login_required
def ajax_fechar_caixa():
    data = request.get_json() or {}
    observacao = data.get("observacao", "").strip()
    valor_contado = float(data.get("valor_contado") or 0)
    turno = data.get("turno", "").strip()
    usuario = session.get("username", "Desconhecido")

    conn = get_db_connection()

    # 🔒 Impede fechamento duplicado para o mesmo operador no dia
    ja_fechado = conn.execute("""
        SELECT COUNT(*) AS qtd FROM fechamentos
        WHERE DATE(data_hora) = DATE('now','localtime') AND usuario = ?
    """, (usuario,)).fetchone()["qtd"]
    if ja_fechado:
        conn.close()
        return jsonify({
            "status": "error",
            "msg": f"⚠️ O operador {usuario} já realizou o fechamento hoje."
        })

    # 🔹 Totais do dia (somente desse operador)
    dados = conn.execute("""
        SELECT 
            SUM(total) AS total_vendas,
            SUM(desconto) AS total_descontos,
            SUM(recebido) AS total_recebido,
            SUM(troco) AS total_troco
        FROM caixa
        WHERE DATE(data_hora) = DATE('now','localtime')
          AND usuario = ?
    """, (usuario,)).fetchone()

    total_vendas    = dados["total_vendas"] or 0
    total_descontos = dados["total_descontos"] or 0
    total_recebido  = dados["total_recebido"] or 0
    total_troco     = dados["total_troco"] or 0

    # 🔹 Recalcula total líquido real
    total_liquido = conn.execute("""
        SELECT 
            SUM(
                CASE 
                    WHEN forma_pagamento = 'Dinheiro' THEN (recebido - troco)
                    ELSE recebido
                END
            ) AS liquido
        FROM caixa
        WHERE DATE(data_hora) = DATE('now','localtime')
          AND usuario = ?
    """, (usuario,)).fetchone()["liquido"] or 0

    # 🔹 Grava fechamento
    conn.execute("""
        INSERT INTO fechamentos (
            usuario, turno, total_vendas, total_descontos,
            total_recebido, total_troco, total_liquido, observacao
        ) VALUES (?,?,?,?,?,?,?,?)
    """, (
        usuario, turno, total_vendas, total_descontos,
        total_recebido, total_troco, total_liquido, observacao
    ))
    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "msg": f"💰 Fechamento ({turno}) de {usuario} salvo com sucesso! Total líquido R$ {total_liquido:.2f}"
    })

@app.route("/ajax_reabrir_fechamento/<int:fechamento_id>", methods=["POST"])
@admin_required
def ajax_reabrir_fechamento(fechamento_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM fechamentos WHERE id=?", (fechamento_id,))
    conn.commit()
    conn.close()
    return jsonify({"status":"ok","msg":"🔓 Fechamento reaberto com sucesso."})

@app.route("/exportar_fechamentos_excel")
@admin_required
def exportar_fechamentos_excel():
    """Exporta todos os fechamentos para Excel (.xlsx)."""
    conn = get_db_connection()
    df = pd.read_sql_query("""
        SELECT id AS 'ID',
               data_hora AS 'Data/Hora',
               usuario AS 'Usuário',
               total_vendas AS 'Total de Vendas (R$)',
               total_descontos AS 'Descontos (R$)',
               total_recebido AS 'Recebido (R$)',
               total_troco AS 'Troco (R$)',
               total_liquido AS 'Total Líquido (R$)',
               observacao AS 'Observação'
        FROM fechamentos
        ORDER BY data_hora DESC
    """, conn)
    conn.close()

    if df.empty:
        flash("Nenhum fechamento encontrado para exportar.", "info")
        return redirect(url_for("fechamento_caixa_page"))

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Fechamentos")
    output.seek(0)

    nome = f"fechamentos_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=nome,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# -------------------------
# Start
# -------------------------
if __name__ == "__main__":
    init_db_custom()
    #app.run(debug=True, host="0.0.0.0")
    serve(app, host="0.0.0.0", port=5000)  # import serve from waitress

