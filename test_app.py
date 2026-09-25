import io
import re
import tempfile
import unittest

from PIL import Image
from flask import g
from werkzeug.security import generate_password_hash

from app import Animal, PRINCIPAL_EMAIL, Story, User, create_app, db, migrate_animal_fields, migrate_story_fields, adoption_ranking


class AppTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False,
                               'UPLOAD_FOLDER': self.folder.name})
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        db.session.add_all([User(email=PRINCIPAL_EMAIL, password_hash=generate_password_hash('OwnerPass123')),
                            User(email='helper@example.com', password_hash=generate_password_hash('HelperPass123'))])
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.folder.cleanup()

    def login(self, owner=True):
        return self.client.post('/login', data={'email': PRINCIPAL_EMAIL if owner else 'helper@example.com',
                                               'password': 'OwnerPass123' if owner else 'HelperPass123'})

    def test_pages_and_protection(self):
        for path in ('/', '/sobre', '/adotar', '/doar', '/depoimentos', '/login'):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.assertEqual(self.client.get('/adotar/999').status_code, 404)
        self.login()
        for path in ('/admin', '/admin/animais/novo', '/admin/historias/nova', '/admin/acessos', '/admin/senha'):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_crud(self):
        self.login(False)
        data = dict(name='Lua', age_value='1', age_unit='anos', sexo='Fêmea', size='Pequeno', temperament='Calmo',
                    status='Disponível', history='História de teste', vaccinated='on')
        image = io.BytesIO()
        Image.new('RGB', (20, 20), 'white').save(image, 'PNG')
        image.seek(0)
        self.assertEqual(self.client.post('/admin/animais/novo', data={**data, 'photo': (image, 'cat.png')}).status_code, 302)
        animal = db.session.query(Animal).one()
        self.assertEqual(animal.age_months, 12)
        self.assertEqual(animal.formatted_age, '1 Ano')
        self.assertEqual(animal.sexo, 'Fêmea')
        self.assertTrue(animal.photo.endswith('.jpg'))
        for path in ('/', '/adotar', f'/adotar/{animal.id}', f'/admin/animais/{animal.id}/editar', '/admin'):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.client.post(f'/admin/animais/{animal.id}/editar', data={**data, 'status': 'Adotado'})
        self.assertEqual(animal.status, 'Adotado')
        self.client.post('/admin/historias/nova', data=dict(title='Novo lar', author='Maria', body='História de teste'))
        story = db.session.query(Story).one()
        self.assertEqual(self.client.get('/depoimentos').status_code, 200)
        self.assertEqual(self.client.get(f'/admin/historias/{story.id}/editar').status_code, 200)
        self.client.post(f'/admin/historias/{story.id}/editar', data=dict(title='Lar feliz', author='Maria', body='Atualização'))
        self.assertEqual(story.title, 'Lar feliz')
        self.client.post(f'/admin/historias/{story.id}/excluir')
        self.client.post(f'/admin/animais/{animal.id}/excluir')
        self.assertEqual(db.session.query(Animal).count(), 0)
        self.assertEqual(db.session.query(Story).count(), 0)

    def test_age_units_sex_and_validation(self):
        self.login()
        data = dict(name='Lua', age_value='2', age_unit='anos', sexo='Fêmea',
                    size='Pequeno', temperament='Calmo', status='Disponível', history='Teste')
        self.assertEqual(self.client.post('/admin/animais/novo', data=data).status_code, 302)
        animal = db.session.query(Animal).one()
        self.assertEqual(animal.age_months, 24)
        for path in ('/', '/adotar', '/admin', f'/adotar/{animal.id}'):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn('2 Anos', html)
            self.assertIn('Fêmea', html)
        self.assertIn('data-age="24"', self.client.get('/adotar').get_data(as_text=True))
        for value, unit, expected in [('6', 'meses', '6 Meses'), ('1', 'meses', '1 Mês'),
                                       ('1', 'anos', '1 Ano'), ('0', 'meses', '0 Meses')]:
            response = self.client.post(f'/admin/animais/{animal.id}/editar',
                                        data={**data, 'age_value': value, 'age_unit': unit, 'sexo': 'Macho'})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(animal.formatted_age, expected)
            self.assertEqual(animal.sexo, 'Macho')
        for invalid in [dict(sexo=''), dict(sexo='Outro'), dict(age_unit='dias'),
                        dict(age_value='-1'), dict(age_value='1.5'), dict(age_value='abc'),
                        dict(age_value='41'), dict(age_value='481', age_unit='meses')]:
            response = self.client.post(f'/admin/animais/{animal.id}/editar', data={**data, **invalid})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(animal.age_months, 0)
            self.assertEqual(animal.sexo, 'Macho')
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.client.post('/admin/animais/novo', data=data).status_code, 400)

    def test_existing_database_migration(self):
        db.session.remove()
        db.drop_all()
        with db.engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE animal (id INTEGER PRIMARY KEY, age_months INTEGER NOT NULL)')
            connection.exec_driver_sql('INSERT INTO animal (id, age_months) VALUES (1, 18)')
        migrate_animal_fields()
        migrate_animal_fields()
        with db.engine.connect() as connection:
            row = connection.exec_driver_sql('SELECT age_months, age_unit, sexo FROM animal').one()
        self.assertEqual(tuple(row), (18, 'meses', None))

    def test_permissions_and_accounts(self):
        self.login(False)
        self.assertEqual(self.client.get('/admin/acessos').status_code, 403)
        self.assertEqual(self.client.post('/admin/acessos', data={}).status_code, 403)
        self.assertEqual(self.client.post('/admin/acessos/1/excluir').status_code, 403)
        self.client.post('/logout')
        self.login()
        self.assertEqual(self.client.post('/admin/acessos/1/excluir').status_code, 403)
        self.assertEqual(self.client.post('/admin/acessos', data=dict(email='new@example.com', password='NewPassword123')).status_code, 302)
        self.client.post('/admin/acessos/2/excluir')
        self.assertIsNone(db.session.get(User, 2))
        self.client.post('/admin/senha', data=dict(current_password='OwnerPass123', new_password='ChangedPass123'))
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.assertEqual(self.client.post('/login', data=dict(email=PRINCIPAL_EMAIL, password='ChangedPass123')).status_code, 302)

    def public_data(self, **changes):
        image = io.BytesIO()
        Image.new('RGB', (20, 20), 'white').save(image, 'PNG')
        image.seek(0)
        return dict(author='Maria', pet_name='Lua', body='Relato privado pendente',
                    photo=(image, '../../cat.png'), **changes)

    def test_public_validation(self):
        for field, value in [('author', ''), ('author', 'a' * 101), ('pet_name', ' '),
                             ('pet_name', 'a' * 101), ('body', ''), ('body', 'a' * 10001),
                             ('photo', (io.BytesIO(b'not an image'), 'cat.png')),
                             ('photo', 'https://example.com/cat.png')]:
            data = self.public_data()
            data[field] = value
            self.assertEqual(self.client.post('/depoimentos/novo', data=data).status_code, 400)
        self.assertEqual(db.session.query(Story).count(), 0)

    def test_pending_approval_and_csrf(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.client.post('/depoimentos/novo', data=self.public_data()).status_code, 400)
        html = self.client.get('/depoimentos').get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        data = self.public_data(csrf_token=token)
        data.update(approved='1', adoption_confirmed='1', source='admin')
        response = self.client.post('/depoimentos/novo', data=data, follow_redirects=True)
        self.assertIn('Aguarde a aprovação', response.get_data(as_text=True))
        story = db.session.query(Story).one()
        self.assertFalse(story.approved)
        self.assertFalse(story.adoption_confirmed)
        self.assertEqual(story.source, 'public')
        self.assertEqual(story.title, 'Adoção de Lua')
        self.assertRegex(story.photo, r'^[a-f0-9]{32}\.jpg$')
        self.assertNotIn(story.body, self.client.get('/depoimentos').get_data(as_text=True))
        path = f'/admin/historias/{story.id}/aprovar'
        self.assertEqual(self.client.post(path, data={'csrf_token': token}).status_code, 302)
        self.assertFalse(story.approved)
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.login(False)
        # This test holds an app context; Flask-WTF caches tokens on g.
        g.pop('csrf_token', None)
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.client.post(path).status_code, 400)
        html = self.client.get('/admin').get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        self.assertEqual(self.client.get(path).status_code, 405)
        self.assertEqual(self.client.post(path, data={'csrf_token': token}).status_code, 302)
        self.assertTrue(story.approved)
        self.assertTrue(story.adoption_confirmed)
        html = self.client.get('/depoimentos').get_data(as_text=True)
        self.assertIn(story.body, html)
        self.assertIn('Maria — 1', html)
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client.post(f'/admin/historias/{story.id}/editar', data=dict(title=story.title, author=story.author, body='Revisado'))
        self.assertFalse(story.approved)
        self.assertFalse(story.adoption_confirmed)

    def test_ranking_and_legacy_confirmation(self):
        stories = [Story(title='Teste', author=name, pet_name='Lua', body='Texto',
                         approved=True, adoption_confirmed=True)
                   for name in ['Maria Silva', '  MARIA   silva ', 'Zelia', 'Ana']]
        stories.extend([Story(title='Antiga', author='Antiga', body='Texto', approved=True,
                              adoption_confirmed=False),
                        Story(title='Pendente', author='Pendente', pet_name='Lua', body='Texto',
                              approved=False, adoption_confirmed=True)])
        db.session.add_all(stories)
        db.session.commit()
        self.assertEqual(adoption_ranking(stories), [dict(name='Maria Silva', count=2),
                                                     dict(name='Ana', count=1), dict(name='Zelia', count=1)])
        self.login()
        legacy = stories[-2]
        self.client.post(f'/admin/historias/{legacy.id}/aprovar')
        self.assertFalse(legacy.adoption_confirmed)
        self.client.post(f'/admin/historias/{legacy.id}/animal', data={'pet_name': 'Sol'})
        self.client.post(f'/admin/historias/{legacy.id}/aprovar')
        self.assertTrue(legacy.adoption_confirmed)

    def test_unchecked_booleans_and_display(self):
        self.login()
        data = dict(name='Lua', age_value='1', age_unit='anos', sexo='Fêmea', size='Pequeno',
                    temperament='Calmo', status='Disponível', history='Teste')
        self.client.post('/admin/animais/novo', data={**data, 'vaccinated': 'on', 'castrated': 'on'})
        animal = db.session.query(Animal).one()
        for path in ('/admin', f'/adotar/{animal.id}'):
            self.assertIn('Sim', self.client.get(path).get_data(as_text=True))
        self.client.post(f'/admin/animais/{animal.id}/editar', data=data)
        db.session.expire_all()
        self.assertIs(animal.vaccinated, False)
        self.assertIs(animal.castrated, False)
        detail = self.client.get(f'/adotar/{animal.id}').get_data(as_text=True)
        self.assertIn('<dt>Vacinação</dt><dd>Não</dd>', detail)
        self.assertIn('<dt>Castração</dt><dd>Não</dd>', detail)
        admin = self.client.get('/admin').get_data(as_text=True)
        self.assertIn('Vacinação: Não', admin)
        self.assertIn('Castração: Não', admin)

    def test_story_migration(self):
        db.session.remove()
        db.drop_all()
        with db.engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE story (id INTEGER PRIMARY KEY, title VARCHAR(150) NOT NULL, author VARCHAR(100) NOT NULL, body TEXT NOT NULL, photo VARCHAR(80))')
            connection.exec_driver_sql("INSERT INTO story VALUES (1, 'Titulo', 'Autora', 'Texto', 'foto.jpg')")
        migrate_story_fields()
        migrate_story_fields()
        story = db.session.get(Story, 1)
        self.assertEqual((story.title, story.author, story.body, story.photo), ('Titulo', 'Autora', 'Texto', 'foto.jpg'))
        self.assertIsNone(story.pet_name)
        self.assertEqual(story.source, 'admin')
        self.assertTrue(story.approved)
        self.assertFalse(story.adoption_confirmed)
        self.assertEqual(adoption_ranking([story]), [])

    def test_public_rate_limit(self):
        app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                          'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': True,
                          'RATELIMIT_STORAGE_URI': 'memory://', 'UPLOAD_FOLDER': self.folder.name})
        with app.app_context():
            db.create_all()
            client = app.test_client()
            for _ in range(5):
                self.assertEqual(client.post('/depoimentos/novo', data={}).status_code, 400)
            self.assertEqual(client.post('/depoimentos/novo', data={}).status_code, 429)
            db.session.remove()
            db.drop_all()

    def test_invalid_input_and_csrf(self):
        self.login()
        self.client.post('/admin/animais/novo', data=dict(name='Invalid', age_months='-1'))
        self.assertEqual(db.session.query(Animal).count(), 0)
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.client.post('/logout').status_code, 400)


if __name__ == '__main__':
    unittest.main()