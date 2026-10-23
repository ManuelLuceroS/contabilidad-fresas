# Mi Contabilidad

Aplicación web en español para un negocio comercial. Django 5.2 LTS sirve las pantallas y valida las operaciones; SQLite guarda la información localmente y PostgreSQL permite un despliegue con varios procesos. No requiere Node para instalar o ejecutar.

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

Los CSV se abren con Excel (UTF-8 con BOM, separador punto y coma). No se genera `.xlsx` nativo. El PDF de ventas agrupa cada venta con su propia tabla de productos: cantidad sin ceros sobrantes, libras totales, precio y subtotal; al pie de cada venta aparece su total y al final, el resumen general por producto. Los PDF se descargan directamente desde el servidor. También puede usar Imprimir → Guardar como PDF.

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
