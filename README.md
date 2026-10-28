# Mi Contabilidad

Aplicación web en español para un negocio comercial. Django 5.2 LTS sirve las pantallas y valida las operaciones; SQLite guarda la información localmente y PostgreSQL permite un despliegue con varios procesos. No requiere Node para instalar o ejecutar.

## Organización del código

- `config/settings.py`: configuración local y de producción mediante variables de entorno.
- `config/urls.py`: rutas de la aplicación.
- `ledger/models.py`: entidades, relaciones, restricciones y cálculo de saldos.
- `ledger/forms.py`: campos y validaciones de los formularios.
- `ledger/views.py`: permisos, filtros y respuestas a las solicitudes del navegador.
- `ledger/services.py`: registro de ventas y abonos con transacciones y protección contra duplicados.
- `ledger/reporting.py`: totales de ventas y agrupación por producto.
- `ledger/exports.py`: generación de los reportes CSV y PDF.
- `ledger/templates/` y `ledger/static/`: pantallas, estilos e interacción en el navegador.
- `ledger/tests.py` y `config/test_settings.py`: pruebas contables, de acceso y de configuración de producción.

Por ejemplo, al registrar una venta, `config/urls.py` dirige la solicitud a
`sale_new` en `ledger/views.py`. La vista comprueba los permisos y llama a
`create_sale` en `ledger/services.py`, que valida los productos, calcula los
importes y guarda la venta junto con su pago inicial dentro de una transacción.

Para ejecutar las pruebas desde el entorno virtual:

```sh
python manage.py test ledger config.test_settings --noinput
python manage.py makemigrations --check --dry-run
```

## Instalación y primer administrador

Requisitos: Python 3.12–3.14. En macOS/Linux, desde esta carpeta:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py initialize
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

Abra http://127.0.0.1:8000 e ingrese con el usuario o el correo y la contraseña del administrador creado. `createsuperuser` pide la contraseña de forma interactiva: no hay credenciales predeterminadas. Los datos permanecen en `db.sqlite3` al cerrar sesión, reiniciar o actualizar. `initialize` es idempotente y solo agrega medios de pago, categorías editables y el grupo Operadores; no crea clientes, productos o movimientos ficticios.

En Windows: `py -m venv .venv` y `.venv\Scripts\activate`, luego los mismos comandos `python`.

## Abrir fácilmente en este Mac

Haga doble clic en **Mi Contabilidad.app** en el Escritorio. La aplicación inicia el servidor local en segundo plano si está detenido y abre el navegador automáticamente. Si el servidor ya está funcionando, lo reutiliza. No necesita abrir la Terminal ni escribir comandos. Después de reiniciar el equipo, basta con volver a abrir esa aplicación.

El usuario, la contraseña y los datos siguen siendo los mismos. La carpeta del proyecto debe permanecer en `/Users/marianagomez/karen/contabilidad`, pues el acceso apunta a esa instalación. Los mensajes técnicos quedan en `logs/server.log`.

Como alternativa, la carpeta del proyecto incluye `Iniciar Mi Contabilidad.command`. El archivo anterior `Iniciar Nexo.command` también continúa funcionando y delega en el nuevo acceso.

## Funcionalidades

- Autenticación por usuario o correo, cierre por POST con CSRF, contraseñas con hash, bloqueo de 15 minutos tras cinco errores por identificador y sesiones de ocho horas.
- Clientes con datos opcionales, búsqueda, edición, inactivación, historial de ventas y abonos y extracto con saldos inicial, acumulado y final.
- Productos por unidades o por libras; peso fijo por presentación o peso ingresado en cada venta. Precio, unidad, nombre y pesos quedan congelados en el detalle vendido.
- Ventas de múltiples productos, consecutivo único, pagos parciales y comprobantes internos imprimibles y en PDF.
- Cartera y abonos con distribución obligatoriamente automática de la deuda más antigua a la más nueva. Cada comprobante muestra la distribución final. Se rechazan pagos superiores a la deuda y aplicaciones a otros clientes.
- Reportes de ventas por cliente y fechas, exclusivamente de lo vendido, con cantidades, libras, total por venta y resumen final por producto. Los abonos y saldos se consultan en cartera y estados de cuenta. Ordenamiento con clic en encabezados, búsqueda por cliente o número y exportación CSV compatible con Excel y PDF.
- Gastos con categorías editables e inactivables, filtros de día/semana/mes o fechas, total por categoría, PDF, CSV y auditoría de cambios con antes/después. Ediciones simultáneas se detectan por revisión.
- Panel con ventas/gastos del día y mes, cartera actual, recaudos del periodo, clientes/productos activos, gráfico comparativo y mayores deudores.
- Navegación adaptable, formatos COP, impresión sin menú y mensajes de confirmación.

Los CSV se abren con Excel (UTF-8 con BOM, separador punto y coma). Los reportes de ventas conservan CSV/PDF; el módulo de nómina adicional genera `.xlsx` nativo. El PDF de ventas agrupa cada venta con su propia tabla de productos: cantidad sin ceros sobrantes, libras totales, precio y subtotal; al pie de cada venta aparece su total y al final, el resumen general por producto. Los PDF se descargan directamente desde el servidor. También puede usar Imprimir → Guardar como PDF.

## Reglas financieras e integridad

El servidor calcula con `Decimal`; los importes se redondean a dos decimales con `ROUND_HALF_UP` por renglón. Las cantidades nuevas solo admiten enteros positivos. El peso por presentación admite hasta tres decimales; se conserva el detalle de pesos de ventas históricas sin modificarlo. Cada importe admite hasta $999.999.999.999,99; el peso total por renglón admite hasta 999.999.999,999999 lb, límites que conservan precisión también con SQLite. El cálculo visual orienta al usuario; el servidor vuelve a calcular todo usando el catálogo, sin confiar en precios o totales enviados por el navegador.

Una venta por peso calcula `cantidad × libras por presentación × precio por libra`. Diez canastas de 16 lb a $2.000/lb generan 160 lb y $320.000. El precio fijo del catálogo se usa incluso si se manipula el formulario.

Una venta de $320.000 con pago inicial de $100.000 crea una venta, un pago y una aplicación de $100.000. Un abono posterior de $70.000 agrega otro pago y aplicación. Saldo final: $150.000. Los recaudos no generan ventas nuevas.

Las transacciones agrupan consecutivo, venta, renglones, pago inicial y auditoría. Los cambios de cartera se serializan por cliente; SQLite usa transacciones `IMMEDIATE`, espera de bloqueo y reintentos acotados. PostgreSQL usa bloqueos de fila. Los tokens UUID únicos hacen idempotentes los reenvíos. Las claves foráneas protegidas, restricciones de valores y unicidad de aplicaciones conservan el historial. No hay rutas para borrar o alterar ventas/abonos existentes; no se permite eliminarlos desde el administrador.

Los abonos posteriores permiten fecha entre la creación del cliente y hoy; solo se aplican a ventas que ya existían en esa fecha. Dentro de una misma fecha, el extracto intercala ventas y pagos por su momento real de registro. Por ejemplo: venta 1, su pago inicial, venta 2 y un abono posterior. Los pagos iniciales identifican la venta a la que corresponden. El extracto de un rango conserva el saldo de movimientos anteriores. El reporte de ventas muestra solo operaciones de venta. Para la deuda actual use cartera y para un saldo histórico use la fecha final del extracto.

La cartera presenta total vendido, total abonado (incluidos los pagos iniciales) y saldo pendiente. El extracto conserva el saldo inicial del periodo y su pie presenta ventas, abonos y saldo final: `saldo inicial + ventas - abonos`. No se suman los saldos acumulados de las filas ni los precios unitarios. No se calcula utilidad: faltan costos de mercancía. Tampoco se presenta como saldo de caja.

Para consultar ventas de un rango: abra **Reportes**, seleccione **Desde** y **Hasta**, elija cliente o todos y pulse **Consultar**. Pantalla, PDF y CSV comparten esos filtros. El resumen final agrupa por producto y configuración histórica de unidad/peso; usa los precios y pesos congelados en los detalles. Cada tabla operativa muestra totales al pie donde corresponde (cantidades, libras, importes, pagos o deuda), incluidos los comprobantes, el borrador de venta y los gastos. Los historiales completos del cliente se etiquetan como tales y conservan sus propios totales, separados del periodo consultado.


## Usuarios y permisos

La navegación de uso diario es para un solo usuario y no muestra una sección para crear usuarios. El acceso administrativo técnico de Django permanece disponible en su URL para mantenimiento.

Una instalación corresponde a **un solo negocio**, con catálogo y cartera compartidos entre sus usuarios autorizados. No es un servicio multiempresa. Use instalaciones y bases separadas para distintos negocios.

El administrador maneja usuarios y grupos en `/admin/`. Para agregar un operador: crear usuario, asignar grupo **Operadores** y mantener activo. No necesita acceso staff. Ese grupo puede consultar y registrar las operaciones y editar catálogos y gastos. Para limitarlo, cree grupos con permisos Django `view`, `add` y `change` por entidad. Cada ruta comprueba permisos; el panel requiere permisos de consulta de ventas, pagos, gastos, productos y clientes. El menú es común: una opción sin permisos responde 403. Los movimientos guardan quién los registró; la auditoría no es editable desde la aplicación.

Use correos únicos entre los usuarios si desean iniciar sesión por correo. Si el identificador coincide con varias cuentas, se rechaza el acceso para evitar ambigüedad. La aplicación no envía correos de recuperación: el administrador restablece contraseñas desde Django admin.

## Variables de entorno

`.env` no se versiona. `.env.example` muestra la configuración.

- `DEBUG`: `true` solo local; `false` en producción.
- `SECRET_KEY`: aleatoria y permanente en producción. Genere con `python -c 'import secrets; print(secrets.token_urlsafe(64))'`. En local se genera `.dev-secret` privado automáticamente.
- `DATABASE_URL`: opcional; sin ella se usa SQLite local. PostgreSQL: `postgresql://usuario:clave@host:5432/nexo`. Codifique caracteres especiales de usuario/contraseña para URL.
- `ALLOWED_HOSTS`: hosts separados por coma, sin protocolo.
- `CSRF_TRUSTED_ORIGINS`: orígenes HTTPS separados por coma, incluyendo protocolo.
- `TRUST_PROXY=true`: solo detrás de un proxy propio que reemplace `X-Forwarded-Proto`. Activa la detección de HTTPS.

Con `DEBUG=false`, se exigen clave secreta y HTTPS, cookies seguras, HSTS y hosts autorizados. No publique el servidor de desarrollo. No hay claves secretas en el frontend. Proteja también el acceso del sistema operativo a la base, respaldos y `.env`.

## Pruebas y verificaciones

```sh
pip install -r requirements-dev.txt
python manage.py check
python manage.py test --verbosity 2
python manage.py makemigrations --check --dry-run
```

La suite cubre A–G y validaciones: cantidades/pesos, valores negativos y no finitos, sobreabonos, pagos iniciales excesivos, duplicados, concurrencia, FIFO obligatorio, rechazo de distribución manual, orden intercalado del extracto, cantidades enteras, protección contra borrado, históricos de producto, reversión transaccional, fechas, auditoría de gastos, edición concurrente, autenticación, bloqueo, CSRF, permisos y respuestas PDF/CSV. Usa una base temporal independiente. Las pruebas de navegador adicionales se describen en `VERIFICACION.md`.

## Despliegue en internet

Se incluyen Dockerfile y Compose para PostgreSQL con volumen persistente. No se ha desplegado en un proveedor ni configurado dominio o TLS en esta entrega.

1. En un servidor Linux con Docker/Compose, copie el proyecto y cree `.env` con `SECRET_KEY`, `POSTGRES_PASSWORD` (aleatoria, segura para URL), `ALLOWED_HOSTS=contabilidad.ejemplo.com`, `CSRF_TRUSTED_ORIGINS=https://contabilidad.ejemplo.com`. No suba ese archivo a git.
2. Construya e inicialice:

```sh
docker compose build
docker compose up -d db
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py initialize
docker compose run --rm web python manage.py createsuperuser
docker compose run --rm web python manage.py check --deploy
docker compose up -d web
```

3. Ponga Nginx/Caddy con certificado TLS delante de `127.0.0.1:8000`. El puerto de la aplicación no está expuesto en todas las interfaces. Configure el proxy para conservar Host y reemplazar `X-Forwarded-Proto` con el protocolo real. Ejemplo Nginx, dentro de un bloque `server` HTTPS con certificado y clave previamente instalados:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
}
```

Redirija HTTP a HTTPS en otro bloque. Compruebe acceso por HTTPS, login, creación de operaciones y descargas. WhiteNoise sirve los estáticos recolectados durante la construcción. La fuente externa es opcional: sin internet se usa la fuente del sistema. No existe dependencia de internet para registrar operaciones.

4. Antes de cada actualización haga respaldo, construya la versión nueva, aplique migraciones y reinicie web. No ejecute `docker compose down -v`: borraría el volumen de PostgreSQL. Los secretos y la base anterior no se reemplazan al construir la imagen.

Para un proveedor administrado: use PostgreSQL persistente, las mismas variables, `python manage.py migrate` como paso de publicación y `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`. Configure HTTPS y proxy confiable según el proveedor. No use SQLite en un disco efímero ni en varias réplicas.

## Respaldos y recuperación

### SQLite local

```sh
python manage.py backup_db --directory backups
```

El comando usa la API de respaldo de SQLite y comprueba integridad. Funciona incluso con la aplicación abierta. Cada archivo tiene nombre único y permisos 0600. Prográmelo diariamente con cron/launchd, copie respaldos cifrados fuera del equipo y conserve, por ejemplo, 30 diarios y 12 mensuales. Guarde también `.env` y la clave secreta en un gestor de secretos.

Para recuperar: detenga **todos** los procesos web, haga respaldo del estado actual, verifique la copia con `sqlite3 archivo.sqlite3 'PRAGMA integrity_check;'`, preserve el archivo actual y reemplace `db.sqlite3` con la copia elegida. No deje archivos WAL/SHM antiguos junto a una base reemplazada. Ejecute `python manage.py migrate`, verifique un extracto y reinicie. Pruebe primero en otra carpeta con `DATABASE_URL=sqlite:////ruta/absoluta/copia.sqlite3`.

### PostgreSQL / Docker

Desde el host, con el servicio de base activo:

```sh
mkdir -p backups
docker compose exec -T db pg_dump -U nexo -d nexo -Fc > backups/nexo.dump
chmod 600 backups/nexo.dump
```

Use nombres con fecha para no sobrescribir copias. El comando Django `backup_db` también soporta PostgreSQL si el equipo tiene el ejecutable `pg_dump` instalado (el contenedor web no lo incluye). Mantenga copias cifradas externas o respaldos administrados con recuperación puntual.

Para ensayar recuperación sin reemplazar la base existente:

```sh
docker compose exec db createdb -U nexo nexo_recuperada
docker compose exec -T db pg_restore -U nexo -d nexo_recuperada --no-owner < backups/nexo.dump
```

Compruebe los saldos conectando una instancia aislada a `nexo_recuperada`. Para usarla en producción, detenga web, respalde el estado actual, cambie `DATABASE_URL` a esa base y reinicie con la versión compatible de la aplicación. Pruebe la restauración periódicamente y después de cambios de esquema. Un archivo de respaldo sin ensayo de recuperación no basta.

## Alcance y ampliaciones

Implementados los módulos operativos solicitados. No incluye facturación electrónica DIAN, inventario/costo de mercancía, contabilidad de partida doble, saldos a favor, anulación/reversión de operaciones o `.xlsx` nativo. Los pagos superiores a la deuda se rechazan. No se debe corregir el historial mediante SQL: una futura función de reversión debe crear movimientos compensatorios auditados. El despliegue en un servidor real, dominio, certificados, programación de respaldos y validación bajo carga productiva dependen de la infraestructura elegida. La suite también se verificó contra PostgreSQL 17 en un contenedor aislado; todavía debe validarse la infraestructura de destino antes de cargar datos reales.

## Despliegue en Vercel

Use el preset **Django**, raíz del repositorio y los comandos automáticos de
instalación/build (quite overrides de Docker, gunicorn y migraciones en build).
`manage.py` y `config.wsgi.application` ya son los puntos de entrada correctos.
Vercel importa los ajustes durante el build: un error de configuración puede
aparecer como `Failed to read Django application settings from .../manage.py`.
Busque la excepción Python anterior en el log completo; no cambie DEBUG para
ocultarla. En particular, `DEBUG=false` sin `SECRET_KEY` produce
`RuntimeError: Configure SECRET_KEY en producción`.

Configure estas variables en **Production**, disponibles tanto en build como en
runtime, y cree un nuevo deployment después de guardarlas:

```dotenv
DEBUG=false
ALLOWED_HOSTS=contabilidad-fresas.vercel.app
CSRF_TRUSTED_ORIGINS=https://contabilidad-fresas.vercel.app
TRUST_PROXY=true
SECRET_KEY=<clave aleatoria privada y estable>
DATABASE_URL=postgresql://USUARIO:CLAVE@HOST:5432/BASE?sslmode=require
```

Genere SECRET_KEY con `python -c 'import secrets; print(secrets.token_urlsafe(64))'`
y guárdela únicamente en el gestor de variables de Vercel. No use el texto entre
ángulos como valor. Use la URL real de un PostgreSQL externo persistente; codifique
los caracteres especiales del usuario/contraseña según el formato URL. Prefiera
la conexión con pool que ofrezca su proveedor para funciones serverless.
No regenere SECRET_KEY en cada build. No escriba secretos en vercel.json ni Git.

ALLOWED_HOSTS lleva nombres sin esquema ni rutas; CSRF_TRUSTED_ORIGINS lleva
orígenes con https://. Separe valores adicionales con comas. Para un dominio
personalizado agregue su host y origen HTTPS a ambas variables. No habilite todos
los subdominios vercel.app. Preview debe usar una base de datos separada, su propia
clave y sus hosts explícitos; no comparta datos contables con previews de PR.
TRUST_PROXY habilita el reconocimiento de HTTPS detrás del proxy de Vercel y evita
bucles de redirección. Fuera de un proxy de confianza déjelo en false.

### Estáticos y comprobación

Vercel ejecuta `collectstatic` automáticamente cuando existe STATIC_ROOT y sirve
/static/ desde su CDN. En producción se generan nombres con hash y compresión
mediante WhiteNoise. No hacen falta rutas catch-all ni un servidor gunicorn.
Para una comprobación local con las variables de producción cargadas de forma
segura en el entorno (y no en un archivo versionado):

```sh
python manage.py check --deploy --fail-level WARNING
python manage.py collectstatic --noinput
```

Compruebe que /ingresar/ responde 200 por HTTPS, / redirige al login, los enlaces
CSS/JS generados responden 200 y el formulario de acceso admite un POST del mismo
origen sin error CSRF. Nunca active DEBUG en el dominio público.

### PostgreSQL, migraciones y datos existentes

SQLite se permite solo en desarrollo. En producción los ajustes fallan si falta
DATABASE_URL o apunta a SQLite: guardar un archivo en una función Vercel no es
persistencia. PostgreSQL debe tener copias de seguridad automáticas externas y
una política de recuperación verificada; guardar backups dentro de Vercel tampoco
es persistencia. El comando backup_db requiere pg_dump para PostgreSQL y un destino
durable fuera de la función.

Ejecute las migraciones desde una máquina/CI de confianza con acceso al PostgreSQL
correcto y las variables de producción cargadas, una vez por versión, antes de
promover el deployment. No ejecute migrate en cada petición ni en builds paralelos:

```sh
python manage.py migrate --noinput
# Solo para una instalación nueva sin datos importados:
python manage.py initialize
python manage.py createsuperuser
```

Si ya hay información en SQLite, no cree simplemente una base vacía. Detenga las
escrituras, localice el archivo original que contiene los datos y haga una copia
consistente con `python manage.py backup_db --directory /ruta/segura`. Si solo
existía dentro de una función ya descartada, configurar PostgreSQL no recupera ese
archivo: necesitará una copia previa. No suba SQLite ni sus exportaciones a Git.

Ensaye la migración sobre una base PostgreSQL vacía y separada. Desde la copia
SQLite local, con DEBUG=true y DATABASE_URL sin definir, exporte a un archivo
privado (contiene datos contables y hashes de contraseñas):

```sh
umask 077
python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission --exclude admin.logentry \
  --output /ruta/segura/contabilidad.json
```

Después, con las variables de PostgreSQL del destino cargadas:

```sh
python manage.py migrate --noinput
python manage.py loaddata /ruta/segura/contabilidad.json
```

Antes de reabrir escrituras compare usuarios, clientes, ventas, pagos, gastos,
saldos y totales de reportes entre origen y destino; pruebe crear y consultar una
operación. Haga un backup del destino y conserve el origen para recuperación.
No ejecute initialize antes de importar una copia con sus propias categorías y
medios de pago. Redépliegue y compruebe que los datos permanecen tras otro deploy.

## Trabajo sin internet y sincronización (computador local)

La versión web de Vercel sigue necesitando internet. Esta adaptación permite usar
una **instalación local de Django y SQLite** sin conexión, con sincronizador en
segundo plano. No es todavía un APK ni una app de iPhone, ni convierte una pestaña
de Vercel en una aplicación offline. El lanzador incluido funciona en macOS;
`sync_cloud` usa bloqueo de archivo Unix (macOS/Linux).

### Preparación de la nube

1. Respalde la base de producción y despliegue el código con la migración `0004`.
   Ejecute `python manage.py migrate` contra la base correcta en su proceso de
   publicación, fuera del build de Vercel.
2. Cree un usuario técnico dedicado, activo, con permisos `view` para clientes,
   productos, medios, categorías, ventas, pagos y gastos, y `add` para ventas,
   pagos y gastos. No necesita ser staff ni superusuario.
3. Configure en Vercel `OFFLINE_NODE=false`, `SYNC_USER` con ese nombre de usuario,
   `SYNC_BUSINESS` con un identificador permanente del negocio y `SYNC_TOKEN`
   aleatorio privado de al menos 32 caracteres. Puede generarlo con
   `python -c 'import secrets; print(secrets.token_urlsafe(48))'`.
   Conserve PostgreSQL, HTTPS y las demás variables existentes.
4. Publique una nueva versión. `/api/sync/` acepta exclusivamente POST autenticado
   con Bearer token; el token nunca se envía al navegador ni aparece en la interfaz.

### Preparación del computador

Use **otra instalación y una base SQLite nueva**, no la base local con movimientos
existentes. La inicialización se niega a mezclar automáticamente esos datos.
Respalde cualquier instalación anterior con `backup_db` antes de preparar otra.
No copie la URL PostgreSQL de producción a la configuración local.

Configure el `.env` local con `DEBUG=true`, `OFFLINE_NODE=true`, una
`DATABASE_URL=sqlite:////ruta/absoluta/fresas-local.sqlite3`,
`ALLOWED_HOSTS=localhost,127.0.0.1`, `TRUST_PROXY=false`, el mismo `SYNC_BUSINESS`
y `SYNC_TOKEN` de la nube, y `SYNC_URL=https://contabilidad-fresas.vercel.app`
(o su dominio real). Proteja `.env`, la base y los respaldos con los permisos del
sistema operativo. La identidad del negocio debe ser idéntica en ambos extremos.

Desde la instalación local, con su entorno virtual activo:

```sh
python manage.py migrate
python manage.py createsuperuser
python manage.py sync_cloud
python scripts/open_app.py
```

La primera sincronización requiere internet y descarga el catálogo y el historial
completo. Las contraseñas no se descargan: el usuario local se crea con
`createsuperuser`; los autores de nube sin cuenta local reciben cuentas sin
contraseña utilizable, sin privilegios. Los usuarios locales existentes conservan
su contraseña y permisos. No reutilice un nombre de usuario de otro negocio.
El lanzador abre la aplicación y arranca `sync_cloud --watch`, que intenta
sincronizar cada `SYNC_INTERVAL` segundos (mínimo 30, predeterminado 120).
Para iniciar con terminales separadas, use `runserver 127.0.0.1:8001 --noreload`
y `python manage.py sync_cloud --watch`.

### Comportamiento y límites

- Se pueden registrar ventas, abonos y gastos sin conexión. La sesión y los datos
  permanecen en el equipo; el inicio de sesión funciona con la contraseña local.
- Clientes, productos, precios, medios y categorías se administran en la nube.
  La aplicación local bloquea sus cambios, incluidos los POST del administrador.
  Los gastos existentes también se editan desde la nube en esta versión.
- Un registro local sin recibo de sincronización es un movimiento pendiente.
  Se envían en orden de registro, primero las ventas y luego sus abonos cuando
  corresponde. El pago inicial se envía con su venta, nunca dos veces.
- El servidor recalcula importes, valida precios/presentaciones vigentes y aplica
  abonos a la cartera real. Conserva la fecha original de la venta y de su pago
  inicial. UUID y recibo transaccional evitan duplicados cuando la conexión se
  corta después de que el servidor confirmó la operación.
- Si cambió el precio o el peso fijo, se inactivó un producto, o un abono supera
  la deuda disponible, se detiene la cola. Los movimientos quedan guardados y el
  error aparece en **Estado de datos**. Requiere revisión del administrador;
  todavía no existe una pantalla para resolver o anular pendientes conflictivos.
  No borre la base ni edite el historial mediante SQL para resolverlo.
- Solo cuando no quedan pendientes se reemplaza el historial local por una copia
  coherente de la nube, dentro de una transacción SQLite. Si se registra algo
  durante la descarga, se conserva y se pospone el reemplazo. El catálogo se
  actualiza junto al historial; mientras haya un conflicto puede quedar desactualizado.
- Los consecutivos de venta locales son provisionales y pueden cambiar al recibir
  el consecutivo definitivo de nube. No use recibos locales como numeración fiscal.
  La cartera offline refleja la última copia más los movimientos de ese equipo;
  otros movimientos de nube aparecen al terminar la sincronización.
- Esta versión admite **un único computador offline por negocio**. No copie su
  base/configuración a varios dispositivos. La app local requiere el proceso local
  funcionando; una futura versión móvil necesitará almacenamiento y empaquetado
  para el sistema operativo elegido. La descarga completa está pensada para un
  negocio pequeño; todavía no usa sincronización incremental del historial.
- Mantenga respaldos locales: los pendientes aún no están protegidos por las
  copias de seguridad de PostgreSQL. Cerrar el navegador no borra los datos.

Pruebas adicionales: `python manage.py test ledger.test_sync --noinput`.
La activación real requiere configurar ambas instalaciones y probar primero con
una base de ensayo. No basta con desplegar este código en Vercel para que un
computador o teléfono ya pueda trabajar sin conexión.

## App instalable en celulares (Android y iPhone)

La ruta **`/movil/` del dominio HTTPS** ofrece la app web instalable. El menú
principal incluye **App sin internet**. En teléfonos usa IndexedDB para los datos
y un service worker para abrir la interfaz sin red; no requiere un computador
encendido ni expone la clave técnica `SYNC_TOKEN`. Esta opción complementa la
instalación SQLite del computador. No es un APK ni un paquete nativo de App Store.

1. Con internet, inicia sesión con un usuario autorizado y abre `/movil/`.
2. Pulsa **Sincronizar** y espera la confirmación, el nombre de cuenta y la fecha
   de la copia. Espera también el mensaje **App preparada para abrir sin internet**.
3. Android: usa Instalar/Agregar a pantalla de inicio en el navegador. iPhone:
   Safari → Compartir → Agregar a inicio. Abre el acceso recién agregado con red
   y sincroniza otra vez: el almacenamiento del acceso instalado puede ser distinto.
4. Antes de usar datos reales, activa modo avión, cierra y vuelve a abrir ese acceso,
   registra una venta de ensayo y comprueba que siga pendiente después de reabrir.
   Al recuperar conexión abre la app, inicia sesión si venció y sincroniza.

Se registran ventas de varios productos por unidades o peso, abonos y gastos.
Los cálculos locales usan enteros de precisión arbitraria y redondeo por renglón;
la nube vuelve a validar todos los importes, permisos y catálogo. No se actualizan
precios de un pendiente silenciosamente. Un conflicto detiene el envío conservando
la cola. Los abonos se validan con la deuda local y nuevamente con la deuda real.
El catálogo se descarga de la nube y no tiene formularios de edición en el móvil.

La sincronización se intenta al abrir, recuperar red, volver a la app y cada dos
minutos mientras está visible. No se promete sincronización con la app cerrada:
iOS limita el trabajo de fondo. La sesión se renueva con internet; perderla no
borra los pendientes. Una copia móvil pertenece a una cuenta y negocio: cambiar
de cuenta bloquea su envío y visualización hasta volver a la cuenta original.
La protección del acceso offline depende del bloqueo del dispositivo. IndexedDB
no cifra por sí mismo los datos y quien accede al perfil del navegador puede verlos.
No use navegación privada ni borre los datos del sitio mientras haya pendientes.
La opción de respaldo descarga la cola en JSON para recuperación asistida; no
incluye importación automática ni es un archivo de Excel.

Pueden trabajar teléfonos independientes y un único computador SQLite para el
negocio. Sin internet no conocen los movimientos de otros dispositivos, así que
sus saldos son provisionales. Un sobreabono concurrente se rechaza en la nube y
requiere revisión; no se elimina ni se ajusta automáticamente.

### Instalación local aislada preparada en este Mac

`python scripts/local_app.py setup` crea `.offline/.env` privado y una base nueva,
aplica migraciones y prepara medios/categorías. Conserva las cuentas de administrador
locales existentes sin copiar movimientos ni modificar la base anterior. La clave
técnica generada permanece fuera de Git. `.offline/` contiene información privada.

- `python scripts/local_app.py open`: abre el servidor local en el puerto 8002 y
  arranca el sincronizador. También se incluye **Abrir Fresas sin internet.command**.
- `python scripts/local_app.py sync`: primer intento manual, con el sincronizador
  detenido. Si hay uno activo, su bloqueo evita duplicarlo.
- `python scripts/local_app.py user`: crea un administrador si no había ninguno.
- `python scripts/local_app.py check`: verifica la configuración aislada.

Para completar la activación, configure en Vercel `SYNC_BUSINESS`, `SYNC_TOKEN`
y `SYNC_USER` con los valores privados de `.offline/.env`, mantenga
`OFFLINE_NODE=false`, aplique `migrate` y ejecute `provision_sync` contra la base
correcta de nube. Este comando crea un usuario técnico sin contraseña interactiva,
con los permisos mínimos de lectura y registro. No utilice un administrador humano
como `SYNC_USER`. Después publique la versión y verifique la primera sincronización
completa desde el computador. No exponga el servidor local a internet ni copie
el token a teléfonos: los teléfonos usan su propia sesión normal de usuario.

Pruebas: `python manage.py test ledger config.test_settings --noinput` incluye
API móvil, permisos, CSRF, reintentos y navegación de acceso. Antes de la activación
real, valide también el acceso instalado en los teléfonos concretos del negocio.

## Nómina, fumigación y comprobantes compartidos

Esta ampliación utiliza la misma aplicación Django, autenticación, diseño y base de
datos. Las migraciones **0005** (entidades, relaciones y restricciones agrícolas)
y **0006** (permisos adicionales del grupo Operadores) son aditivas. No reemplazan
clientes, productos de venta, ventas, abonos, usuarios ni gastos. Los productos
fitosanitarios tienen un catálogo propio, separado de los productos vendidos.

Para actualizar otra instalación, primero respalde su base correcta, instale las
dependencias y aplique las migraciones desde su entorno de confianza:

```sh
python manage.py backup_db --directory backups/pre-agricola
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py check
```

No es necesario volver a ejecutar `initialize` en una instalación existente. La
migración agrega los permisos agrícolas de consulta, registro y cambio al grupo
Operadores, sin quitar sus permisos previos. Otros grupos deben recibir permisos
explícitos desde la administración. La configuración global de extras queda para
el administrador o usuarios con `view_payrollsettings` y `change_payrollsettings`.
Los modelos agrícolas no tienen edición directa en Django admin: las operaciones
pasan por los formularios, validaciones, bloqueos y auditoría de la aplicación.

### Uso de nómina

En **Nómina → Configuración de tarifas**, el administrador debe definir una tarifa
extra por hora (incluso cero, si así corresponde) o las horas ordinarias por día y
un factor explícito para derivarla del valor del día. No hay salarios, recargos ni
jornadas predeterminados. El minuto se paga proporcionalmente a la hora. Cada
trabajador tiene su tarifa diaria individual y fecha de ingreso.

En **Registro diario**, seleccione una fecha y registre quién trabajó, horas,
minutos y observaciones. Los minutos se normalizan: 90 minutos son 1 h 30 min. La
asistencia es única por trabajador y fecha; no se permiten extras sin día trabajado,
fechas futuras ni días trabajados anteriores al ingreso. El límite técnico es 24
horas extras acumuladas por registro; no es una recomendación de jornada.

La tarifa diaria y la regla de extras se congelan cuando se **crea** la asistencia.
Cambiar después el trabajador o la configuración solo afecta asistencias nuevas;
una asistencia antigua editada conserva sus tarifas originales. Para cargar fechas
pasadas, configure la tarifa correspondiente antes de crear sus registros. No se
infiere una tarifa histórica inexistente. En la regla derivada, el importe se
calcula directamente con la tarifa diaria, el factor, las horas ordinarias y los
minutos enteros: se redondea a centavos por día, sin redondear primero la tarifa
horaria de referencia mostrada. Todos los cálculos usan `Decimal`.

**Generar nómina** admite cualquier rango no futuro. Guarda una copia del detalle
diario, nombres, identificación, tarifas, reglas y totales, en estado **Generada**.
Las asistencias incluidas quedan protegidas y no se liquidan de nuevo en otra nómina
activa, incluso si sus períodos se solapan. Los reenvíos de la misma operación no
crean otra liquidación. Puede confirmar el pago, registrar su fecha y exportar un
Excel nativo `.xlsx` con hojas **Resumen** y **Detalle diario**. El archivo contiene
valores históricos y cifras numéricas conciliadas; los textos del usuario no se
convierten en fórmulas de Excel.

Para corregir una liquidación, anúlela indicando el motivo, corrija su asistencia
y genere una nueva. La liquidación original y su auditoría permanecen intactas.
Solo un superusuario puede anular una nómina pagada. Cada nómina nueva con total positivo crea un **único gasto** de categoría Nómina,
con fecha del fin del período y referencia `NO-<id>`. Hasta confirmar el pago aparece
con medio **Pendiente de pago de nómina**. Al confirmar el pago debe elegir un medio
real: se actualiza ese mismo gasto, sin crear otro. Si ya se pagó al generar, puede
marcarlo y seleccionar el medio en el formulario de generación. La anulación excluye
el gasto de los totales y de la copia offline, conservando los registros y la auditoría.
El gasto vinculado no se edita manualmente: sus correcciones se administran desde la
nómina. Las nóminas anteriores a esta integración no crean gastos retroactivos para
evitar duplicar gastos manuales históricos. Un total cero no genera gasto ni avisos.

### Uso de fumigación

En **Programación de fumigación** administre productos, ingrediente, categoría,
unidad, restricciones e intervalo opcional. Para guardar un intervalo debe indicar
su fuente técnica o el responsable agrícola. No se incluyen dosis ni frecuencias
predeterminadas.

Un registro admite varios productos con cantidad y unidad, fecha/hora, área,
responsable y observaciones. Puede guardarse como **Programada** o **Realizada**.
La próxima fecha es opcional: al seleccionar productos con intervalo aparecen
fechas orientativas, que solo rellenan la próxima fecha al pulsarlas. La programación
se confirma al guardar el formulario. No se asigna automáticamente una frecuencia
común a productos con intervalos diferentes. Una próxima aplicación copia productos
y cantidades como **previstos**, editables antes de confirmar lo realmente aplicado.

El calendario mensual permite cambiar de mes, consultar cada día/evento y filtrar
por área y producto; en teléfonos se desplaza horizontalmente. Las listas permiten
filtrar además por fechas. Se distinguen realizadas, programadas, vencidas y
anuladas; se señala la proximidad dentro de tres días (solo un indicador visual).
Llegar a la fecha nunca cambia una programación a realizada. Abra **Editar /
confirmar aplicación realizada**, revise fecha, cantidades y responsable y cambie
el estado explícitamente. Las programaciones se pueden editar o anular con motivo;
las aplicaciones realizadas se conservan sin edición. Se auditan los cambios con
sus datos anteriores y posteriores.

### PDF y WhatsApp

Al abrir el comprobante de una venta guardada se prepara el PDF desde los datos del
servidor. Puede consultarlo, descargarlo, imprimirlo o pulsar **Enviar por WhatsApp**.
El PDF incluye identificación histórica del cliente, consecutivo, fecha, detalles
de unidades/peso, medio, pago inicial, total abonado y saldo **actual**, sin cambiar
las reglas contables. La venta permanece guardada y el PDF se puede regenerar en
consultas posteriores; no depende de un archivo temporal ni de un servicio externo.

El botón usa el diálogo nativo de compartir archivos cuando el navegador lo admite:
el usuario elige WhatsApp y confirma allí. Cuando no está disponible, descarga el
PDF y explica cómo adjuntarlo manualmente. **Abrir conversación de WhatsApp** utiliza
el teléfono del cliente con un mensaje preparado y no adjunta ni envía el PDF.
No se afirma envío confirmado. No se publica una URL de la venta: los endpoints
PDF siguen requiriendo sesión y permisos de ventas/pagos.

Puede configurar `BUSINESS_NAME` para el encabezado del PDF y
`WHATSAPP_COUNTRY_CODE` para números locales de diez dígitos (predeterminado `57`,
Colombia). Los números internacionales con `+` conservan su prefijo. No hace falta
una API externa para este flujo. El envío oficial por WhatsApp Business Platform está integrado y requiere activar
la cuenta, las credenciales y las plantillas descritas a continuación.
La compatibilidad real del diálogo de compartir depende del navegador/dispositivo;
la alternativa de descarga permanece disponible.

Los módulos agrícolas se administran exclusivamente en la **instalación principal**.
El protocolo offline del computador y la app `/movil/` conservan su alcance anterior
(ventas, abonos, gastos y sus catálogos). Las rutas agrícolas de una réplica
`OFFLINE_NODE=true` muestran esta limitación y bloquean cambios para evitar datos
que no se sincronizarían.

### Archivos y verificación de la ampliación

- `ledger/farm_models.py`, importado desde `models.py`: ocho entidades nuevas.
- `ledger/farm_forms.py`, `farm_services.py`, `farm_views.py`: validación,
  transacciones serializadas, control de revisión, permisos y auditoría.
- `ledger/farm_exports.py`: Excel nativo con tarifas históricas y detalle diario.
- `ledger/receipt.py`, `views.py`, `templates/ledger/sale_detail.html` y
  `static/ledger/receipt.js`: comprobante privado y opciones de compartir.
- `templates/ledger/{attendance,payroll_*,worker_history,spray_*,farm_*}.html`,
  `static/ledger/{app.css,farm.js}`, `templates/ledger/base.html` y `config/urls.py`:
  navegación, formularios, calendario y diseño adaptable.
- `migrations/0005_*`, `migrations/0006_*`, `middleware.py`,
  `management/commands/initialize.py`, `config/settings.py`, `.env.example` y
  `requirements.txt`: esquema, permisos, alcance offline y dependencias.
- `ledger/test_farm.py`: cálculos, exportaciones, permisos, validaciones,
  reintentos, concurrencia, aplicaciones y comprobantes de contado/crédito.

```sh
python manage.py test ledger config.test_settings --noinput
python manage.py makemigrations --check --dry-run
python manage.py check
```

La verificación de desarrollo también ensayó la migración sobre una copia SQLite,
comparando íntegramente las tablas anteriores, renderizó el PDF y las pantallas en
anchos de escritorio y móvil, y ejecutó los flujos JavaScript de productos, fechas
sugeridas y compartir/descargar con APIs simuladas. No envió mensajes reales a
clientes ni comprobó una integración oficial de WhatsApp. PostgreSQL y los
navegadores concretos de los usuarios requieren verificación en su despliegue.


## WhatsApp desde el número de la empresa y gastos de nómina

La ampliación `0007` agrega teléfonos de trabajadores, autorización de los contactos,
el vínculo de gasto de nómina y una cola privada de comprobantes. `0008` agrega al
grupo Operadores el permiso `send_whatsappmessage`. No modifica las cifras históricas,
no registra gastos retroactivos ni envía mensajes de ventas o nóminas antiguas.
Los nuevos campos de contacto tienen valores predeterminados en la base para que
la versión anterior pueda seguir escribiendo durante un despliegue gradual.

El remitente configurado es **+57 3115893850**. Un teléfono escrito en configuración
no basta para enviar desde él: el número debe estar vinculado a una cuenta de
**WhatsApp Business Platform / Cloud API**. La app WhatsApp Business por sí sola no
proporciona credenciales de Cloud API. El sistema verifica en Meta que el identificador
de teléfono configurado corresponda al remitente antes de cargar/enviar documentos.
No cambia el destinatario al teléfono de la empresa: usa el teléfono de cada cliente
o trabajador.

### Activación por el administrador

1. Vincular/verificar el número con Meta y obtener su `WHATSAPP_PHONE_NUMBER_ID` y un
   token de usuario de sistema con los permisos de mensajería necesarios. Usar la
   configuración privada de producción en Vercel; no pegar secretos en el chat,
   documentos compartidos, código ni `.env.example`.
2. Crear dos plantillas de utilidad aprobadas, con **cabecera DOCUMENT** y cuerpo con
   **tres parámetros de texto posicionales**. Ejemplos de contenido para solicitar
   aprobación (los nombres reales aprobados se configuran en Vercel):
   - Venta: `Hola {{1}}, adjuntamos el comprobante {{2}} por {{3}}.`
   - Nómina: `Hola {{1}}, adjuntamos el resumen de nómina del período {{2}}. {{3}}.`
   Los parámetros enviados son nombre, consecutivo/período e importe/resumen,
   respectivamente. Elegir el idioma aprobado en `WHATSAPP_TEMPLATE_LANGUAGE`.
3. Configurar `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
   `WHATSAPP_SALE_TEMPLATE`, `WHATSAPP_PAYROLL_TEMPLATE`,
   `WHATSAPP_SENDER_NUMBER=573115893850` y `WHATSAPP_ENABLED=true`.
   La versión Graph API está fijada mediante `WHATSAPP_API_VERSION` (base `v25.0`);
   verificarla y actualizarla al mantener la integración.
4. Configurar el webhook de Meta en
   `https://contabilidad-fresas.vercel.app/api/whatsapp/webhook/`, con
   `WHATSAPP_VERIFY_TOKEN` privado y `WHATSAPP_APP_SECRET` de la aplicación de Meta.
   Suscribir los estados de mensajes. Sin webhook, una solicitud puede aparecer
   aceptada, pero no se afirma que haya llegado al destinatario.
5. En **Clientes** y **Trabajadores**, registrar su WhatsApp y la autorización para
   recibir comprobantes/resúmenes. El sistema vuelve a comprobar la autorización
   al enviar; una revocación bloquea los mensajes que aún no se han enviado.

Fuentes de integración: [documentación oficial de Meta en Postman](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api)
y [política de mensajería de WhatsApp](https://whatsappbusiness.com/policy/).

### Operación y límites de entrega

Las ventas nuevas con autorización crean su comprobante en la cola dentro de la misma
transacción que registra la venta. Una venta previa puede prepararse con el botón
**Preparar envío automático al cliente**, sin crear otra venta. Las nóminas nuevas
preparan un PDF **por trabajador**, con sus días, extras, importes y estado real del
pago. Nunca se envía al trabajador la nómina completa ni información de sus compañeros.
Una nómina generada sin pago confirmado se identifica como pendiente; confirmar el
pago prepara su resumen definitivo y cancela el borrador aún no enviado.

Con la integración activa, la pantalla procesa la cola inmediatamente, de un
comprobante por solicitud. Además, `vercel.json` incluye un procesador diario a las
13:00 UTC, compatible con el plan Hobby del proyecto, para pendientes cuando se cerró
la pantalla. El endpoint `/api/whatsapp/cola/` solo acepta llamadas con
`Authorization: Bearer <CRON_SECRET>`; la clave se configura en Vercel y nunca se
expone al navegador. Cada ejecución limita el lote y el tiempo de procesamiento;
una cola extensa puede requerir varias ejecuciones o un plan/procesador de mayor
frecuencia. No se promete procesamiento inmediato con la pantalla cerrada.

Los PDF se cargan como medios privados a Meta y se adjuntan por identificador; no se
publican enlaces a facturas o sueldos. La cola guarda el documento de cada operación
para conservar su contenido original, separado de las consultas posteriores.
Los estados son pendiente, bloqueado, en proceso, aceptado, enviado, entregado,
leído, rechazado, por verificar o cancelado. Los callbacks se validan con HMAC de
la aplicación y se comprueba el destinatario. Los eventos repetidos o fuera de orden
no retroceden un estado de entrega confirmado.

Los reintentos de una operación no generan otra fila de envío. Si un corte de red
impide conocer el resultado, queda **Envío por verificar** y se detiene el reintento
automático. Revise WhatsApp antes de autorizar un nuevo intento: una API externa no
permite garantizar exactamente una entrega tras perder su respuesta. Los intentos
interrumpidos se pueden revisar desde la pantalla. No se permite anular una nómina
mientras tenga un envío en curso. Un mensaje ya entregado no se puede retirar al
anular; su registro se conserva.

Mientras no se vincule Meta, los documentos siguen disponibles para descargar y
compartir manualmente. Para que salgan del 3115893850, abra WhatsApp con esa cuenta;
el navegador no puede seleccionar ni verificar una cuenta remitente. La interfaz
muestra esta limitación y no registra estos enlaces como envíos confirmados.

Pruebas adicionales: `ledger/test_whatsapp_payroll.py` valida gastos únicos,
anulaciones, pago confirmado, documentos individuales, consentimiento, remitente,
plantillas, callbacks, permisos y resultados de red inciertos, con la API simulada.
No envía pruebas a números reales ni valida credenciales inexistentes.


### Compartir desde WhatsApp normal en el dispositivo

El flujo predeterminado de ventas y nómina funciona sin Cloud API, sin token de Meta
y sin WhatsApp Business. Pulse **Enviar por WhatsApp · PDF y total** en una venta o
**Compartir PDF y total** en el resumen individual del trabajador. El diálogo nativo
incluye el PDF y el mensaje con el total; el usuario elige WhatsApp, el contacto y
confirma el envío desde su cuenta abierta. El sistema no selecciona automáticamente
la cuenta remitente ni confirma la entrega por abrir ese diálogo.

El mensaje de venta contiene su consecutivo y total, además del saldo si está pendiente.
El de nómina contiene solo el nombre, período, días, extras y total de ese trabajador.
Se diferencia total pagado de devengado pendiente, y las nóminas históricas también
se pueden compartir aunque no tengan registros en la cola automática.

Si el navegador no comparte archivos, el botón descarga el PDF. Abra el chat desde
el enlace del cliente/trabajador, que precarga el mensaje con su total, y adjunte el
PDF descargado. También hay **Copiar mensaje con el total**, por si WhatsApp omite
el texto al recibir el archivo desde el diálogo del sistema. Los archivos siguen
requiriendo sesión y permisos; no se crean enlaces públicos a facturas ni sueldos.
El panel de configuración/estados de Cloud API aparece solo en instalaciones que
activen esa integración: no es un requisito para compartir desde WhatsApp normal.
