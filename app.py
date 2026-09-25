import os
import secrets
import warnings
import re
from io import BytesIO
from urllib.parse import urlsplit, unquote
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import click
import cloudinary.uploader
import cloudinary.utils
from dotenv import load_dotenv
from flask import Flask, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import inspect, select, true, false
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

if os.environ.get('PYTHON_DOTENV_DISABLED') != '1':
    load_dotenv()
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

def normalize_database_url(value):
    for prefix in ('postgres://', 'postgresql://'):
        if value.startswith(prefix):
            return 'postgresql+psycopg://' + value[len(prefix):]
    return value

def cloudinary_options(value):
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'cloudinary' or not parsed.username or not parsed.password
                or not parsed.hostname or parsed.path not in ('', '/') or parsed.query
                or parsed.fragment or parsed.port
                or not re.fullmatch(r'[A-Za-z0-9_-]+', parsed.hostname)):
            raise ValueError
        return dict(cloud_name=parsed.hostname, api_key=unquote(parsed.username),
                    api_secret=unquote(parsed.password), secure=True)
    except (ValueError, TypeError):
        raise RuntimeError('CLOUDINARY_URL invalida; confira a configuracao privada.') from None

def photo_url(photo):
    if photo and photo.startswith('cloudinary:'):
        public_id = photo[len('cloudinary:'):]
        options = current_app.extensions.get('cloudinary_options')
        if options and re.fullmatch(r'ogle/[a-f0-9]{32}', public_id):
            return cloudinary.utils.cloudinary_url(
                public_id, resource_type='image', type='upload', format='jpg',
                cloud_name=options['cloud_name'], secure=True,
                private_cdn=False, secure_distribution=None, cname=None,
                sign_url=False, url_suffix=None)[0]
        return url_for('static', filename='placeholder.svg')
    return url_for('static', filename='uploads/' + photo if photo else 'placeholder.svg')


def migrate_animal_fields():
    # Additive migration preserves existing ages and leaves unknown sex unset.
    with db.engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table('animal'):
            return
        columns = {column['name'] for column in inspector.get_columns('animal')}
        if 'sexo' not in columns:
            connection.exec_driver_sql('ALTER TABLE animal ADD COLUMN sexo VARCHAR(10)')
        if 'age_unit' not in columns:
            connection.exec_driver_sql("ALTER TABLE animal ADD COLUMN age_unit VARCHAR(5) NOT NULL DEFAULT 'meses'")

def migrate_story_fields():
    # Legacy stories stay published, but never count as confirmed adoptions.
    with db.engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table('story'):
            return
        columns = {column['name'] for column in inspector.get_columns('story')}
        additions = {
            'pet_name': 'VARCHAR(100)',
            'source': "VARCHAR(10) NOT NULL DEFAULT 'admin'",
            'approved': 'BOOLEAN NOT NULL DEFAULT TRUE',
            'adoption_confirmed': 'BOOLEAN NOT NULL DEFAULT FALSE',
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.exec_driver_sql(f'ALTER TABLE story ADD COLUMN {name} {definition}')


def adoption_ranking(stories):
    grouped = {}
    for story in stories:
        if not (story.approved and story.adoption_confirmed and story.pet_name and story.pet_name.strip()):
            continue
        display = ' '.join(story.author.split())
        if not display:
            continue
        key = display.casefold()
        if key not in grouped:
            grouped[key] = {'name': display, 'count': 0}
        grouped[key]['count'] += 1
    return sorted(grouped.values(), key=lambda item: (-item['count'], item['name'].casefold()))


limiter = Limiter(key_func=get_remote_address)
PRINCIPAL_EMAIL = 'astram067@gmail.com'
OFFICIAL_NAME = 'Orfanato Gataria da LuEdu MT - OGLE MT'
ABOUT_TEXT = 'Orfanato Gataria da LuEdu MT - OGLE MT, fundada na data de 15 de setembro de 2023, é uma Associação Civil de direito privado, sem fins econômicos, de caráter organizacional, filantrópico, assistencial, promocional e educacional, e tem como finalidades a defesa, preservação e conservação do meio ambiente e promoção do desenvolvimento sustentável, especialmente através do resgate, tratamento, castração, vacinação, abrigo e promoção de adoção de animais vítimas de maus tratos e abandonos, além da promoção gratuita da saúde, especialmente através da prevenção de zoonoses endêmicas para a população.'
SIZES = ('Pequeno', 'Médio', 'Grande')
TEMPERAMENTS = ('Calmo', 'Brincalhão', 'Tímido', 'Sociável')
STATUSES = ('Disponível', 'Em Tratamento', 'Adotado')
SEXES = ('Macho', 'Fêmea')
AGE_UNITS = ('meses', 'anos')


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    @property
    def is_owner(self):
        return self.email == PRINCIPAL_EMAIL


class Animal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    age_months = db.Column(db.Integer, nullable=False)
    sexo = db.Column(db.String(10), nullable=True)
    age_unit = db.Column(db.String(5), nullable=False, default='meses', server_default='meses')
    size = db.Column(db.String(20), nullable=False)
    temperament = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='Disponível')
    vaccinated = db.Column(db.Boolean, default=False, nullable=False)
    castrated = db.Column(db.Boolean, default=False, nullable=False)
    history = db.Column(db.Text, nullable=False)
    photo = db.Column(db.String(80))


    @property
    def age_value(self):
        return self.age_months // 12 if self.age_unit == 'anos' else self.age_months

    @property
    def formatted_age(self):
        singular, plural = ('Ano', 'Anos') if self.age_unit == 'anos' else ('Mês', 'Meses')
        return f'{self.age_value} {singular if self.age_value == 1 else plural}'

class Story(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    body = db.Column(db.Text, nullable=False)
    photo = db.Column(db.String(80))
    pet_name = db.Column(db.String(100), nullable=True)
    source = db.Column(db.String(10), nullable=False, default='admin', server_default='admin')
    approved = db.Column(db.Boolean, nullable=False, default=True, server_default=true())
    adoption_confirmed = db.Column(db.Boolean, nullable=False, default=False, server_default=false())


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id)) if user_id.isdigit() else None


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        RENDER=os.environ.get('RENDER', '').lower() == 'true',
        CLOUDINARY_URL=os.environ.get('CLOUDINARY_URL'),
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///ogle.db'),
        SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True},
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        RATELIMIT_STORAGE_URI=os.environ.get('RATELIMIT_STORAGE_URI', 'memory://'),
        UPLOAD_FOLDER=str(Path(app.root_path) / 'static' / 'uploads'),
    )
    if test_config:
        app.config.update(test_config)
    app.config['SQLALCHEMY_DATABASE_URI'] = normalize_database_url(app.config['SQLALCHEMY_DATABASE_URI'])
    if app.config['RENDER']:
        if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql+psycopg://'):
            raise RuntimeError('Render exige DATABASE_URL PostgreSQL.')
        if not app.config['CLOUDINARY_URL']:
            raise RuntimeError('Render exige CLOUDINARY_URL.')
        if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY']) < 32:
            raise RuntimeError('Render exige SECRET_KEY estavel com pelo menos 32 caracteres.')
    app.extensions['cloudinary_options'] = cloudinary_options(app.config['CLOUDINARY_URL'])
    if not app.config['SECRET_KEY']:
        if app.config['TESTING']:
            app.config['SECRET_KEY'] = secrets.token_hex(32)
        else:
            Path(app.instance_path).mkdir(exist_ok=True)
            secret_path = Path(app.instance_path) / 'secret.key'
            try:
                with secret_path.open('x') as file:
                    file.write(secrets.token_hex(32))
            except FileExistsError:
                pass
            app.config['SECRET_KEY'] = secret_path.read_text().strip()
    app.jinja_env.globals['photo_url'] = photo_url
    db.init_app(app)
    with app.app_context():
        migrate_animal_fields()
        migrate_story_fields()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Entre para acessar o painel.'
    csrf.init_app(app)
    limiter.init_app(app)

    @app.context_processor
    def institution():
        return dict(official_name=OFFICIAL_NAME, about_text=ABOUT_TEXT,
                    principal_email=PRINCIPAL_EMAIL, pix_key='oglemt29@gmail.com',
                    pix_holder=OFFICIAL_NAME)

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if request.path.startswith(('/admin', '/login')):
            response.headers['Cache-Control'] = 'no-store'
        return response

    for code, message in {400: 'Solicitação inválida ou formulário expirado. Recarregue a página.',
                          403: 'Você não tem permissão para esta ação.',
                          404: 'Esta página não foi encontrada.',
                          413: 'Envie uma imagem de até 6 MB.',
                          429: 'Muitas tentativas. Aguarde o fim do limite de envios e tente novamente.'}.items():
        app.register_error_handler(code, lambda error, c=code, m=message:
                                   (render_template('error.html', code=c, message=m), c))

    def all_rows(model):
        return db.session.scalars(select(model).order_by(model.id.desc())).all()

    def text(name, maximum):
        value = request.form.get(name, '').strip()
        if not value or len(value) > maximum:
            raise ValueError(f'O campo {name} é obrigatório e aceita até {maximum} caracteres.')
        return value

    def upload():
        photo = request.files.get('photo')
        if not photo or not photo.filename:
            return None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(photo.stream) as image:
                    if image.format not in ('JPEG', 'PNG', 'WEBP'):
                        raise ValueError('Use uma imagem JPG, PNG ou WebP.')
                    image = ImageOps.exif_transpose(image).convert('RGB')
                    image.thumbnail((1600, 1600))
                    output = BytesIO()
                    # A fresh image drops EXIF, ICC and other source metadata.
                    clean = Image.new('RGB', image.size)
                    clean.paste(image)
                    clean.save(output, 'JPEG', quality=85)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ValueError('Imagem inválida ou grande demais.') from None
        identifier = uuid4().hex
        options = app.extensions['cloudinary_options']
        if options:
            try:
                output.seek(0)
                result = cloudinary.uploader.upload(
                    output, folder='ogle', public_id=identifier, resource_type='image',
                    type='upload', format='jpg', overwrite=False, unique_filename=False,
                    use_filename=False, timeout=30, **options)
                if (result.get('public_id') != f'ogle/{identifier}'
                        or result.get('resource_type') != 'image'
                        or result.get('format') != 'jpg'):
                    raise ValueError('Unexpected upload response')
                return f'cloudinary:ogle/{identifier}'
            except Exception:
                raise ValueError('Nao foi possivel enviar a foto. Tente novamente mais tarde.') from None
        folder = Path(app.config['UPLOAD_FOLDER'])
        try:
            folder.mkdir(parents=True, exist_ok=True)
            filename = f'{identifier}.jpg'
            (folder / filename).write_bytes(output.getvalue())
            return filename
        except OSError:
            raise ValueError('Nao foi possivel salvar a foto. Tente novamente mais tarde.') from None

    @app.route('/')
    def home():
        animals = db.session.scalars(select(Animal).where(Animal.status == 'Disponível').limit(3)).all()
        return render_template('index.html', animals=animals,
                               total=db.session.query(Animal).count(),
                               adopted=db.session.query(Animal).filter_by(status='Adotado').count())

    @app.route('/sobre')
    def sobre():
        return render_template('sobre.html')

    @app.route('/adotar')
    def adotar():
        return render_template('adotar.html', animals=db.session.scalars(
            select(Animal).where(Animal.status == 'Disponível').order_by(Animal.id.desc())).all())

    @app.route('/adotar/<int:animal_id>')
    def detalhe_animal(animal_id):
        return render_template('detalhe_animal.html', animal=db.get_or_404(Animal, animal_id))

    @app.route('/doar')
    def doar():
        return render_template('doar.html')

    @app.route('/depoimentos')
    def depoimentos():
        return story_page()

    def story_page(status=200):
        stories = db.session.scalars(select(Story).where(Story.approved.is_(True))
                                     .order_by(Story.id.asc())).all()
        return render_template('depoimentos.html', stories=list(reversed(stories)),
                               ranking=adoption_ranking(stories)), status

    @app.post('/depoimentos/novo')
    @limiter.limit('5 per hour')
    def story_submit():
        try:
            author = text('author', 100)
            pet_name = text('pet_name', 100)
            body = text('body', 10000)
            photo = upload()
            if not photo:
                raise ValueError('Escolha uma foto JPG, PNG ou WebP para enviar seu depoimento.')
            db.session.add(Story(title=f'Adoção de {pet_name}', author=author,
                                 pet_name=pet_name, body=body, photo=photo,
                                 source='public', approved=False, adoption_confirmed=False))
            db.session.commit()
            flash('Depoimento recebido! Aguarde a aprovação da equipe antes da publicação e inclusão no ranking.', 'success')
            return redirect(url_for('depoimentos'))
        except ValueError as error:
            flash(str(error), 'error')
            return story_page(400)

    @app.route('/login', methods=['GET', 'POST'])
    @limiter.limit('5 per minute', methods=['POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('admin'))
        if request.method == 'POST':
            email = request.form.get('email', '').strip().lower()
            user = db.session.scalar(select(User).where(User.email == email))
            # A dummy hash keeps unknown accounts on the password-check path too.
            valid = check_password_hash(user.password_hash if user else dummy_hash,
                                        request.form.get('password', ''))
            if user and valid:
                from flask import session
                session.clear()
                session.permanent = True
                login_user(user)
                return redirect(url_for('admin'))
            flash('E-mail ou senha inválidos.', 'error')
        return render_template('login.html')

    dummy_hash = generate_password_hash(secrets.token_urlsafe(24))

    @app.post('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('home'))

    @app.route('/admin')
    @login_required
    def admin():
        return render_template('admin.html', animals=all_rows(Animal), stories=all_rows(Story))

    @app.route('/admin/animais/novo', methods=['GET', 'POST'])
    @app.route('/admin/animais/<int:animal_id>/editar', methods=['GET', 'POST'], endpoint='animal_edit')
    @login_required
    def animal_create(animal_id=None):
        animal = db.get_or_404(Animal, animal_id) if animal_id else None
        if request.method == 'POST':
            try:
                age_unit = text('age_unit', 5)
                if age_unit not in AGE_UNITS:
                    raise ValueError('Selecione uma unidade de idade válida.')
                try:
                    age_value = int(request.form.get('age_value', ''))
                except ValueError:
                    raise ValueError('Informe uma idade inteira válida.') from None
                values = dict(name=text('name', 100), history=text('history', 10000),
                              age_months=age_value * (12 if age_unit == 'anos' else 1),
                              age_unit=age_unit, sexo=text('sexo', 10),
                              size=text('size', 20), temperament=text('temperament', 30),
                              status=text('status', 30), vaccinated='vaccinated' in request.form,
                              castrated='castrated' in request.form)
                if not 0 <= values['age_months'] <= 480:
                    raise ValueError('Informe uma idade entre 0 e 480 meses.')
                if values['sexo'] not in SEXES or values['size'] not in SIZES or values['temperament'] not in TEMPERAMENTS or values['status'] not in STATUSES:
                    raise ValueError('Selecione opções válidas.')
                photo = upload()
                target = animal or Animal()
                for key, value in values.items():
                    setattr(target, key, value)
                if photo:
                    target.photo = photo
                db.session.add(target)
                db.session.commit()
                flash('Animal salvo.', 'success')
                return redirect(url_for('admin'))
            except ValueError as error:
                flash(str(error), 'error')
        return render_template('animal_form.html', animal=animal, sizes=SIZES,
                               temperaments=TEMPERAMENTS, statuses=STATUSES, sexes=SEXES)

    @app.post('/admin/animais/<int:animal_id>/excluir')
    @login_required
    def animal_delete(animal_id):
        db.session.delete(db.get_or_404(Animal, animal_id))
        db.session.commit()
        flash('Animal removido.', 'success')
        return redirect(url_for('admin'))

    @app.route('/admin/historias/nova', methods=['GET', 'POST'])
    @app.route('/admin/historias/<int:story_id>/editar', methods=['GET', 'POST'], endpoint='story_edit')
    @login_required
    def story_create(story_id=None):
        story = db.get_or_404(Story, story_id) if story_id else None
        if request.method == 'POST':
            try:
                values = dict(title=text('title', 150), author=text('author', 100), body=text('body', 10000))
                pet_name = request.form.get('pet_name', story.pet_name or '' if story else '').strip()
                if len(pet_name) > 100 or (story and story.source == 'public' and not pet_name):
                    raise ValueError('Informe o nome do animal com até 100 caracteres.')
                values['pet_name'] = pet_name or None
                photo = upload()
                target = story or Story()
                # Editing a counted report requires a fresh explicit confirmation.
                target.adoption_confirmed = False
                if story and story.source == 'public':
                    target.approved = False
                for key, value in values.items():
                    setattr(target, key, value)
                if photo:
                    target.photo = photo
                db.session.add(target)
                db.session.commit()
                flash('História salva.', 'success')
                return redirect(url_for('admin'))
            except ValueError as error:
                flash(str(error), 'error')
        return render_template('story_form.html', story=story)

    @app.post('/admin/historias/<int:story_id>/aprovar')
    @login_required
    def story_approve(story_id):
        story = db.get_or_404(Story, story_id)
        if not story.author.strip() or not story.pet_name or not story.pet_name.strip():
            flash('Preencha o nome do adotante e do animal antes de confirmar o relato.', 'error')
            return redirect(url_for('story_edit', story_id=story.id))
        story.approved = True
        story.adoption_confirmed = True
        db.session.commit()
        flash('Relato aprovado para publicação e inclusão no ranking de adoções relatadas.', 'success')
        return redirect(url_for('admin'))

    @app.post('/admin/historias/<int:story_id>/animal')
    @login_required
    def story_pet(story_id):
        story = db.get_or_404(Story, story_id)
        try:
            story.pet_name = text('pet_name', 100)
        except ValueError as error:
            flash(str(error), 'error')
            return redirect(url_for('story_edit', story_id=story.id))
        story.adoption_confirmed = False
        if story.source == 'public':
            story.approved = False
        db.session.commit()
        return redirect(url_for('admin'))

    @app.post('/admin/historias/<int:story_id>/excluir')
    @login_required
    def story_delete(story_id):
        db.session.delete(db.get_or_404(Story, story_id))
        db.session.commit()
        flash('História removida.', 'success')
        return redirect(url_for('admin'))

    @app.route('/admin/acessos', methods=['GET', 'POST'])
    @login_required
    def users():
        if not current_user.is_owner:
            abort(403)
        if request.method == 'POST':
            try:
                email = text('email', 254).lower()
                password_value = text('password', 128)
                if len(password_value) < 10 or '@' not in email or '.' not in email.split('@')[-1]:
                    raise ValueError('Informe um e-mail válido e senha com pelo menos 10 caracteres.')
                db.session.add(User(email=email, password_hash=generate_password_hash(password_value)))
                db.session.commit()
                flash('Administrador cadastrado.', 'success')
                return redirect(url_for('users'))
            except IntegrityError:
                db.session.rollback()
                flash('Este e-mail já está cadastrado.', 'error')
            except ValueError as error:
                flash(str(error), 'error')
        return render_template('users.html', administrators=all_rows(User))

    @app.post('/admin/acessos/<int:user_id>/excluir')
    @login_required
    def user_delete(user_id):
        if not current_user.is_owner:
            abort(403)
        user = db.get_or_404(User, user_id)
        if user.is_owner:
            abort(403)
        db.session.delete(user)
        db.session.commit()
        flash('Acesso removido.', 'success')
        return redirect(url_for('users'))

    @app.route('/admin/senha', methods=['GET', 'POST'])
    @login_required
    @limiter.limit('5 per minute', methods=['POST'])
    def password():
        if request.method == 'POST':
            new_password = request.form.get('new_password', '')
            if not check_password_hash(current_user.password_hash, request.form.get('current_password', '')):
                flash('Senha atual incorreta.', 'error')
            elif not 10 <= len(new_password) <= 128:
                flash('A nova senha deve ter entre 10 e 128 caracteres.', 'error')
            else:
                current_user.password_hash = generate_password_hash(new_password)
                db.session.commit()
                logout_user()
                flash('Senha alterada. Entre novamente.', 'success')
                return redirect(url_for('login'))
        return render_template('password.html')

    @app.cli.command('init-db')
    def init_db():
        db.create_all()
        click.echo('Banco inicializado. Execute python seed.py para criar a conta principal.')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=False)