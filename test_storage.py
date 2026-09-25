"""Isolated storage tests: no external services or application data."""
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from werkzeug.security import generate_password_hash, check_password_hash

with patch.dict(os.environ, {'PYTHON_DOTENV_DISABLED': '1', 'DATABASE_URL': 'sqlite://',
                             'SECRET_KEY': 'test-only-key-not-for-production',
                             'RENDER': 'false', 'CLOUDINARY_URL': ''}):
    from app import (Animal, Story, User, db, create_app, photo_url,
                     normalize_database_url, cloudinary_options, PRINCIPAL_EMAIL)
    import seed as seed_module


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.config = dict(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite://',
                           SECRET_KEY='test-key', RENDER=False,
                           CLOUDINARY_URL='cloudinary://dummy:dummy@test-cloud',
                           WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False,
                           UPLOAD_FOLDER=self.folder.name)
        self.app = create_app(self.config)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.folder.cleanup()

    def image(self):
        output = io.BytesIO()
        image = Image.new('RGB', (2000, 1000), 'white')
        exif = Image.Exif()
        exif[270] = 'private metadata'
        image.save(output, 'JPEG', exif=exif)
        output.seek(0)
        return (output, '../../untrusted.jpg')

    def data(self):
        return dict(author='Test', pet_name='Cat', body='Test story', photo=self.image())

    def login(self):
        db.session.add(User(email=PRINCIPAL_EMAIL,
                            password_hash=generate_password_hash('TestPassword123')))
        db.session.commit()
        self.client.post('/login', data=dict(email=PRINCIPAL_EMAIL, password='TestPassword123'))

    def remote(self, stream, **options):
        with Image.open(stream) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.size, (1600, 800))
            self.assertFalse(image.getexif())
        self.assertEqual(options['folder'], 'ogle')
        self.assertRegex(options['public_id'], r'^[a-f0-9]{32}$')
        self.assertTrue(options['secure'])
        self.assertFalse(options['overwrite'])
        self.assertEqual(options['cloud_name'], 'test-cloud')
        return dict(public_id='ogle/' + options['public_id'], resource_type='image', format='jpg')

    def test_remote_story_and_animal_upload(self):
        self.login()
        with patch('app.cloudinary.uploader.upload', side_effect=self.remote) as upload:
            self.assertEqual(self.client.post('/depoimentos/novo', data=self.data()).status_code, 302)
            data = dict(name='Cat', age_value='2', age_unit='meses', sexo='Macho',
                        size='Pequeno', temperament='Calmo', status='Disponível', history='Test',
                        photo=self.image())
            self.assertEqual(self.client.post('/admin/animais/novo', data=data).status_code, 302)
            self.assertEqual(upload.call_count, 2)
        for row in (db.session.query(Animal).one(), db.session.query(Story).one()):
            self.assertRegex(row.photo, r'^cloudinary:ogle/[a-f0-9]{32}$')
            self.assertLessEqual(len(row.photo), 80)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_remote_failure_and_bad_response_never_fall_back(self):
        for result in (RuntimeError('PRIVATE-CREDENTIAL'), {},
                       dict(public_id='unexpected', resource_type='image', format='jpg')):
            with self.subTest(result=type(result).__name__):
                kwargs = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
                with patch('app.cloudinary.uploader.upload', **kwargs):
                    response = self.client.post('/depoimentos/novo', data=self.data())
                self.assertEqual(response.status_code, 400)
                self.assertNotIn('PRIVATE-CREDENTIAL', response.get_data(as_text=True))
                self.assertEqual(db.session.query(Story).count(), 0)
                self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_invalid_image_never_reaches_cloud(self):
        data = self.data()
        data['photo'] = (io.BytesIO(b'not an image'), 'cat.jpg')
        with patch('app.cloudinary.uploader.upload') as upload:
            self.assertEqual(self.client.post('/depoimentos/novo', data=data).status_code, 400)
            upload.assert_not_called()

    def test_failed_remote_edit_preserves_existing_photo(self):
        self.login()
        animal = Animal(name='Cat', age_months=2, size='Pequeno', temperament='Calmo',
                        history='Original', photo='legacy.jpg')
        story = Story(title='Original', author='Test', body='Original', photo='legacy.jpg')
        db.session.add_all([animal, story])
        db.session.commit()
        with patch('app.cloudinary.uploader.upload', side_effect=RuntimeError('private-secret')):
            animal_response = self.client.post(f'/admin/animais/{animal.id}/editar', data=dict(
                name='Changed', age_value='2', age_unit='meses', sexo='Macho', size='Pequeno',
                temperament='Calmo', status='Disponível', history='Changed', photo=self.image()))
            story_response = self.client.post(f'/admin/historias/{story.id}/editar', data=dict(
                title='Changed', author='Test', body='Changed', photo=self.image()))
        for response in (animal_response, story_response):
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('private-secret', response.get_data(as_text=True))
        db.session.expire_all()
        self.assertEqual((animal.name, animal.photo), ('Cat', 'legacy.jpg'))
        self.assertEqual((story.title, story.photo), ('Original', 'legacy.jpg'))
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_local_and_remote_rendering_all_templates(self):
        self.login()
        animal = Animal(name='Cat', age_months=2, size='Pequeno', temperament='Calmo', history='Test')
        story = Story(title='Test', author='Test', body='Test')
        db.session.add_all([animal, story])
        db.session.commit()
        for photo, expected in [('legacy.jpg', '/static/uploads/legacy.jpg'),
                                ('cloudinary:ogle/' + 'a' * 32,
                                 'https://res.cloudinary.com/test-cloud/image/upload/v1/ogle/' + 'a' * 32 + '.jpg')]:
            animal.photo = story.photo = photo
            db.session.commit()
            for route in ('/', '/adotar', f'/adotar/{animal.id}', '/admin',
                          f'/admin/animais/{animal.id}/editar', '/depoimentos',
                          f'/admin/historias/{story.id}/editar'):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, response.get_data(as_text=True), route)

    def test_config_is_per_app(self):
        other = create_app({**self.config, 'CLOUDINARY_URL': 'cloudinary://other:other@other-cloud'})
        local = create_app({**self.config, 'CLOUDINARY_URL': None})
        photo = 'cloudinary:ogle/' + 'a' * 32
        for app, expected in [(self.app, 'test-cloud'), (other, 'other-cloud'), (self.app, 'test-cloud')]:
            with app.test_request_context():
                self.assertIn('/' + expected + '/', photo_url(photo))
        with local.test_request_context():
            self.assertIsNone(local.extensions['cloudinary_options'])
            self.assertEqual(photo_url('old.jpg'), '/static/uploads/old.jpg')

    def test_url_normalization_preserves_query(self):
        suffix = 'user:p%40ss@host/db?sslmode=require&channel_binding=require&x=a%2Fb'
        for scheme in ('postgres://', 'postgresql://', 'postgresql+psycopg://'):
            self.assertEqual(normalize_database_url(scheme + suffix), 'postgresql+psycopg://' + suffix)
        self.assertEqual(normalize_database_url('sqlite://'), 'sqlite://')
        self.assertTrue(db.engine.pool._pre_ping)

    def test_render_requires_configuration_before_connecting(self):
        valid = {**self.config, 'RENDER': True, 'SECRET_KEY': 'x' * 32,
                 'SQLALCHEMY_DATABASE_URI': 'postgresql://dummy:dummy@invalid/db'}
        for changes, message in [({'SQLALCHEMY_DATABASE_URI': 'sqlite://'}, 'DATABASE_URL'),
                                 ({'CLOUDINARY_URL': ''}, 'CLOUDINARY_URL'),
                                 ({'SECRET_KEY': ''}, 'SECRET_KEY'),
                                 ({'SECRET_KEY': 'short'}, 'SECRET_KEY'),
                                 ({'CLOUDINARY_URL': 'invalid-secret'}, 'CLOUDINARY_URL')]:
            with self.assertRaisesRegex(RuntimeError, message):
                create_app({**valid, **changes})
        with self.assertRaises(RuntimeError) as error:
            cloudinary_options('invalid-secret')
        self.assertNotIn('invalid-secret', str(error.exception))

    def test_postgresql_ddl(self):
        for model in (Animal, Story, User):
            ddl = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
            self.assertIn('CREATE TABLE', ddl)
            if model is Story:
                self.assertIn('DEFAULT true', ddl)
                self.assertIn('DEFAULT false', ddl)

    def test_seed_requires_password_and_preserves_owner(self):
        with patch.object(seed_module, 'app', self.app):
            for password in ('', 'short', ' ' * 12, 'x' * 129):
                with patch.dict(os.environ, {'INITIAL_ADMIN_PASSWORD': password}):
                    with self.assertRaisesRegex(RuntimeError, 'INITIAL_ADMIN_PASSWORD'):
                        seed_module.seed()
                self.assertEqual(db.session.query(User).count(), 0)
            with patch.dict(os.environ, {'INITIAL_ADMIN_PASSWORD': 'LongTestPassword123'}):
                seed_module.seed()
            owner = db.session.query(User).one()
            old_hash = owner.password_hash
            self.assertTrue(check_password_hash(old_hash, 'LongTestPassword123'))
            with patch.dict(os.environ, {'INITIAL_ADMIN_PASSWORD': ''}):
                seed_module.seed()
            self.assertEqual(db.session.query(User).one().password_hash, old_hash)