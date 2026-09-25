# Convenções do projeto

- Flask, SQLAlchemy, SQLite e Jinja; interface em português brasileiro.
- Execute Python pelo ambiente `.venv`.
- Testes: `python -m unittest -v`.
- Todas as alterações de dados exigem POST e CSRF.
- Apenas PRINCIPAL_EMAIL gerencia acessos; valide no servidor.
- Nunca apresente dados demonstrativos como resultados reais do abrigo.
- Não versione banco de dados, uploads, segredos ou ambiente virtual.