"""Initialize the database and owner without resetting existing credentials."""
import os

from sqlalchemy import select
from werkzeug.security import generate_password_hash

from app import PRINCIPAL_EMAIL, User, app, db


def seed():
    with app.app_context():
        db.create_all()
        if db.session.scalar(select(User).where(User.email == PRINCIPAL_EMAIL)):
            print('Conta principal existente; senha preservada.')
            return
        password = os.environ.get('INITIAL_ADMIN_PASSWORD', '')
        if not 10 <= len(password.strip()) <= 128:
            raise RuntimeError('Defina INITIAL_ADMIN_PASSWORD com 10 a 128 caracteres para criar a conta principal.')
        db.session.add(User(email=PRINCIPAL_EMAIL, password_hash=generate_password_hash(password)))
        db.session.commit()
        print('Conta principal criada. Altere a senha no primeiro acesso.')


if __name__ == '__main__':
    seed()