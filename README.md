# OGLE MT

Aplicação Flask para o Orfanato Gataria da LuEdu MT, Cuiabá-MT.

## 1. Arquivos no VS Code

Os arquivos já estão nas pastas corretas; não é necessário copiar código.

- `app.py`: modelos SQLite/PostgreSQL, Cloudinary, autenticação, rotas, validação e permissões.
- `seed.py`: criação idempotente da conta principal.
- `templates/`: páginas HTML/Jinja e formulários administrativos.
- `static/style.css`: identidade visual e layout responsivo.
- `static/main.js`: menu móvel, filtros, contadores e cópia PIX.
- `static/placeholder.svg`: ilustração provisória, não uma foto real.
- `requirements.txt`: dependências.
- `test_app.py`: testes automatizados com banco temporário.

## 2. Preparar e iniciar (PowerShell)

Na raiz do projeto, com Python 3.11 ou superior:

Antes do primeiro seed, defina `INITIAL_ADMIN_PASSWORD` privadamente no ambiente
ou no arquivo local `.env`: senha única de 10 a 128 caracteres. Não existe senha
padrão. Sem `DATABASE_URL` e `CLOUDINARY_URL`, o desenvolvimento usa SQLite e fotos
locais. Para HTTP local, use `COOKIE_SECURE=0`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\python.exe app.py
```

Acesse http://127.0.0.1:5000. Para parar, use Ctrl+C.
No VS Code, selecione `.venv` em **Python: Select Interpreter**.

## 3. Administrar

Abra `/login`. Conta principal: `astram067@gmail.com`, com a senha definida privadamente em `INITIAL_ADMIN_PASSWORD`. O seed exige essa variável somente na criação; nunca redefine a senha de uma conta existente. Altere a senha em **Minha senha** quando necessário.

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
- Localmente, o banco padrão é `instance/ogle.db`. Faça backup dele, de `static/uploads` e da chave secreta. Com `DATABASE_URL`, o banco é o serviço configurado. Não publique `.env`, `instance` ou dados pessoais em Git.
- `INITIAL_ADMIN_PASSWORD` é obrigatória para uma nova conta principal; não existe senha inicial embutida.
- CSRF protege todas as ações POST; tentativas de login são limitadas. Senhas usam scrypt via Werkzeug. Não há cadastro público de administradores.
- `create_all` cria tabelas; as migrações aditivas específicas rodam em `create_app`. Para outras evoluções em produção, adote Alembic/Flask-Migrate.
- Links externos de Instagram/WhatsApp dependem dos serviços externos. Cópia automática do PIX exige HTTPS ou localhost; há alternativa manual.

## 6. Render + Neon + Cloudinary

1. No Neon, crie o projeto/banco e copie a **URL completa de conexão** (a opção
	 pooled pode ser usada). Copie somente `postgresql://...`, sem `psql`, aspas
	 externas ou outros comandos. Preserve todos os parâmetros, inclusive
	 `sslmode=require` e `channel_binding=require`, quando fornecidos. A aplicação
	 converte `postgres://` e `postgresql://` para o driver `postgresql+psycopg://`
	 sem alterar usuário, senha codificada, host, banco ou query string.
2. No Cloudinary, copie privadamente a variável no formato
	 `cloudinary://API_KEY:API_SECRET@CLOUD_NAME`. Não use o endereço do dashboard
	 nem uma URL de imagem. Não envie credenciais em chat, capturas ou commits.
3. Crie um Web Service Python no Render apontando para o repositório. Configure
	 Build Command: `pip install -r requirements.txt`.
4. Configure Start Command:
	 `python seed.py && waitress-serve --host=0.0.0.0 --port=$PORT app:app`.
	 Esse comando é para o shell Linux do Render, não para PowerShell. `PORT` é
	 fornecida pelo Render. Se o seed falhar, o servidor não inicia.
5. Na área privada **Environment** do Render, configure:

| Variável | Valor |
| --- | --- |
| `DATABASE_URL` | URL completa do Neon, incluindo parâmetros SSL |
| `CLOUDINARY_URL` | URL privada do Cloudinary, no formato indicado |
| `SECRET_KEY` | Segredo aleatório forte, estável, com pelo menos 32 caracteres |
| `COOKIE_SECURE` | `1` para os cookies de sessão via HTTPS |
| `INITIAL_ADMIN_PASSWORD` | Senha única forte, de 10 a 128 caracteres, para o primeiro seed |

O Render fornece `RENDER=true`. Nesse modo a aplicação recusa SQLite, ausência
de Cloudinary ou chave de sessão ausente/curta, antes de conectar ao banco. Não
desative essa proteção. Preserve `SECRET_KEY` entre deploys; trocá-la invalida
sessões. HTTPS é obrigatório com `COOKIE_SECURE=1`. Depois da primeira criação,
`INITIAL_ADMIN_PASSWORD` pode ser removida; o seed preserva a conta existente.
O arquivo `.env.example` contém apenas exemplos fictícios: não o use sem trocar
os placeholders. Em desenvolvimento sem serviços remotos, omita ambas as URLs.

6. Após implantar, verifique login, cadastro de animal com foto, edição e envio
	 de depoimento. Confirme a imagem HTTPS no Cloudinary e a persistência dos
	 registros após um novo deploy. A validação automatizada deste projeto usa
	 mocks; não certifica suas credenciais, rede ou contas remotas.

### Fotos e dados existentes

- **Não há migração automática de SQLite para Neon nem dos uploads antigos.**
	Um banco Neon vazio começa sem animais e sem histórias. Faça backups e planeje
	uma importação separada, incluindo IDs, sequências e referências das fotos.
- Fotos novas passam por Pillow, limite de tamanho, redução para até 1600 x 1600
	e regravação JPEG sem metadados antes do envio pelo SDK. Pasta `ogle` e IDs UUID
	são definidos no servidor. Falha remota produz mensagem genérica e nunca grava
	uma cópia local como fallback.
- O campo `photo` existente de 80 caracteres armazena `cloudinary:ogle/<uuid>`
	(47 caracteres); não foi necessário alargar colunas. URLs HTTPS são geradas
	pelo SDK. Nomes legados continuam apontando para `/static/uploads/`.
- Fotos legadas só funcionam onde os arquivos antigos estiverem presentes.
	Não dependa do disco efêmero do Render nem versione uploads: transfira-os
	separadamente antes de substituir a instalação antiga.
- Excluir/editar registros não apaga automaticamente imagens antigas locais ou
	remotas. Falha de gravação no banco após um upload também pode deixar uma foto
	sem referência; faça limpeza controlada após backup.
- Migrações aditivas usam `TRUE`/`FALSE`, compatíveis com SQLite e PostgreSQL;
	modelos usam defaults booleanos SQLAlchemy. Conexões usam `pool_pre_ping`.
	Isso não substitui migrações versionadas ou testes em PostgreSQL real.
- Os testes usam bancos em memória e pastas temporárias; desabilitam `.env` antes
	da importação inicial e não precisam das credenciais dos serviços.

## Contatos oficiais

E-mail e PIX: oglemt29@gmail.com. Titular: Orfanato Gataria da LuEdu MT - OGLE MT.
WhatsApp: (65) 9 9363-7766. Instagram: @gatariadaluedumt.