# OGLE MT

Aplicação Flask para o Orfanato Gataria da LuEdu MT, Cuiabá-MT.

## 1. Arquivos no VS Code

Os arquivos já estão nas pastas corretas; não é necessário copiar código.

- `app.py`: modelos SQLite, autenticação, rotas, validação e permissões.
- `seed.py`: criação idempotente da conta principal.
- `templates/`: páginas HTML/Jinja e formulários administrativos.
- `static/style.css`: identidade visual e layout responsivo.
- `static/main.js`: menu móvel, filtros, contadores e cópia PIX.
- `static/placeholder.svg`: ilustração provisória, não uma foto real.
- `requirements.txt`: dependências.
- `test_app.py`: testes automatizados com banco temporário.

## 2. Preparar e iniciar (PowerShell)

Na raiz do projeto, com Python 3.11 ou superior:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\python.exe app.py
```

Acesse http://127.0.0.1:5000. Para parar, use Ctrl+C.
No VS Code, selecione `.venv` em **Python: Select Interpreter**.

## 3. Administrar

Abra `/login`. Conta principal: `astram067@gmail.com`, senha inicial fornecida na solicitação. O seed usa essa senha somente na criação; nunca redefine uma conta existente. Altere a senha imediatamente em **Minha senha**. É possível substituir a senha inicial definindo `INITIAL_ADMIN_PASSWORD` antes de executar o seed.

Somente a conta principal gerencia administradores. Todos os administradores gerenciam animais e histórias. A conta principal não pode ser removida. Cada administrador pode alterar sua própria senha.

Cadastre animais reais com fotos JPG, PNG ou WebP de até 6 MB. As imagens são verificadas e convertidas para JPEG, removendo metadados. Não há animais, depoimentos ou estatísticas históricas inventadas: os contadores refletem os registros atuais, não o total histórico de resgates. Ao excluir um registro, ele deixa de contar. A galeria lista apenas animais disponíveis.

As fotos antigas são preservadas em `static/uploads` ao editar/excluir registros; faça limpeza manual periódica de arquivos sem referência, após backup. Publique fotos e depoimentos somente com autorização dos responsáveis.

## 4. Testar

### Depoimentos e ranking

Visitantes enviam nome do adotante, nome do animal, foto (upload obrigatório) e texto em `/depoimentos`. O POST tem CSRF, validação de tamanho e limite de 5 envios por hora por IP. A foto passa pela mesma validação e conversão segura dos cadastros administrativos.

Relatos públicos ficam pendentes e não aparecem na lista nem no ranking até um administrador revisar e usar **Aprovar publicação e confirmar relato para o ranking**. Relatos inadequados podem ser excluídos. Editar um relato público retira sua publicação e confirmação até nova aprovação. Alterar qualquer relato remove sua confirmação para o ranking.

Histórias antigas e criadas pela equipe continuam publicadas, mas não contam automaticamente: associe o animal na edição, identifique o adotante e confirme explicitamente no painel. O ranking agrupa nomes ignorando maiúsculas/minúsculas e espaços repetidos, ordena por quantidade decrescente e nome em empates. Cada relato confirmado vale uma adoção relatada; não comprova identidade, não deduplica animais e não representa totais oficiais do abrigo. Não contém valores financeiros.

Na inicialização, migrações aditivas preservam dados existentes e acrescentam os campos de animal e de moderação de histórias. Faça backup antes da implantação. Nenhum dado demonstrativo é necessário.

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

## 5. Publicar com segurança

- Nunca use o servidor de desenvolvimento na internet. Exemplo com Waitress: `.\.venv\Scripts\waitress-serve.exe --host=127.0.0.1 --port=8000 app:app`, atrás de proxy HTTPS.
- Configure `SECRET_KEY` com um segredo forte e `COOKIE_SECURE=1` somente com HTTPS. Localmente uma chave persistente é criada em `instance/secret.key`.
- Configure `RATELIMIT_STORAGE_URI` com armazenamento compartilhado (por exemplo Redis, instalando o extra correspondente) para múltiplos processos. O padrão em memória é adequado apenas ao desenvolvimento/instância única e reinicia com o processo.
- O banco é `instance/ogle.db`. Faça backup dele, de `static/uploads` e da chave secreta. Não publique `.env`, `instance` ou dados pessoais em Git.
- Remova a senha inicial conhecida do fluxo de implantação; prefira `INITIAL_ADMIN_PASSWORD`. Revise o seed antes de distribuir o código.
- CSRF protege todas as ações POST; tentativas de login são limitadas. Senhas usam scrypt via Werkzeug. Não há cadastro público de administradores.
- `create_all` cria tabelas; as migrações aditivas específicas rodam em `create_app`. Para outras evoluções em produção, adote Alembic/Flask-Migrate.
- Links externos de Instagram/WhatsApp dependem dos serviços externos. Cópia automática do PIX exige HTTPS ou localhost; há alternativa manual.

## Contatos oficiais

E-mail e PIX: oglemt29@gmail.com. Titular: Orfanato Gataria da LuEdu MT - OGLE MT.
WhatsApp: (65) 9 9363-7766. Instagram: @gatariadaluedumt.