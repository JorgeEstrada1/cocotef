import sys
import os

# Ruta a tu proyecto en PythonAnywhere.
# Cambia 'TU_USUARIO' por tu nombre de usuario de PythonAnywhere.
path = '/home/coteff3d/gestion3d'
if path not in sys.path:
    sys.path.append(path)

# El archivo de la base de datos debe quedar dentro del proyecto.
os.chdir(path)

from app import app as application
application.secret_key = os.environ.get('SECRET_KEY', application.secret_key)
