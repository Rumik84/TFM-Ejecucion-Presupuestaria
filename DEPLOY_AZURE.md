# Despliegue del dashboard en Azure App Service

Arquitectura: **dos recursos separados**.

```
App Service (Linux, corre Streamlit)  ──SSL:5432──►  PostgreSQL Flexible Server (feature store, YA existe)
```

El App Service solo ejecuta el código; los datos siguen en tu Postgres. Toda la
configuración va por **variables de entorno (App Settings)**, nunca en el código.

---

## 0. Requisitos previos (una vez)

```bash
az login
az account set --subscription "<tu-suscripción-Azure-for-Students>"
```

Variables que usaremos:

| Variable        | Valor de ejemplo                                  |
|-----------------|---------------------------------------------------|
| Grupo recursos  | `rg-tfm` (el valor en postgres)                       |
| App Service     | `tfm-dashboard` (debe ser único en azurewebsites) |
| Plan            | `plan-tfm`                                         |
| Postgres host   | `postgres-tfm.postgres.database.azure.com`        |
| Región          | `westeurope` (misma que tu Postgres)              |

---

## 1. Empaquetar el dashboard

```powershell
./deploy.ps1        # genera deploy.zip (~0.1 MB) con src/, config/, .streamlit/, requirements.txt
```

## 2. Crear el servidor web (empieza GRATIS con F1)

```bash
az appservice plan create -n plan-tfm -g rg-tfm --sku F1 --is-linux
az webapp create -g rg-tfm -p plan-tfm -n tfm-dashboard --runtime "PYTHON:3.12"
```

> Para la defensa, sube a B1 (~13 USD/mes, sin arranques en frío):
> `az appservice plan update -g rg-tfm -n plan-tfm --sku B1`
> Al terminar, baja a F1 o borra el plan para dejar de pagar.

## 3. Configurar variables de entorno (conexión a Postgres)

```bash
az webapp config appsettings set -g rg-tfm -n tfm-dashboard --settings \
  DATA_BACKEND=azure \
  PGHOST=postgres-tfm.postgres.database.azure.com \
  PGUSER=adminuser \
  PGDATABASE=postgres \
  PGSSLMODE=require \
  PGPASSWORD='<PASSWORD_ROTADA>' \
  WEBSITES_PORT=8000 \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true
```

## 4. Comando de arranque + WebSockets (Streamlit los necesita)

```bash
az webapp config set -g rg-tfm -n tfm-dashboard --web-sockets-enabled true \
  --startup-file "python -m streamlit run src/dashboard/app.py --server.port 8000 --server.address 0.0.0.0"
```

## 5. Permitir que el App Service llegue a Postgres

Ambos están en Azure → basta la regla "permitir servicios de Azure":

```bash
az postgres flexible-server firewall-rule create -g rg-tfm -n postgres-tfm \
  --rule-name allow-azure --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0
```

## 6. Desplegar

```bash
az webapp deploy -g rg-tfm -n tfm-dashboard --type zip --src-path deploy.zip
```

App disponible en: `https://tfm-dashboard.azurewebsites.net`

## 7. Verificar / depurar

```bash
az webapp log tail -g rg-tfm -n tfm-dashboard     # logs en vivo (Ctrl+C para salir)
```

---

## Controlar el gasto (presupuesto de estudiante)

- **Parar cómputo sin borrar datos:** `az webapp stop -g rg-tfm -n tfm-dashboard`
  (el plan F1 es gratis; en B1, para dejar de pagar hay que bajar a F1 o borrar el plan).
- **Borrar solo el web server** (los datos en Postgres quedan intactos):
  `az webapp delete -g rg-tfm -n tfm-dashboard`

## Seguridad

- **Rota la contraseña** de Postgres (se compartió en chat) y ponla SOLO como App Setting
  `PGPASSWORD` (o, mejor, en Azure Key Vault con referencia).
- Nunca la incluyas en `deploy.zip`, en el código ni en el repositorio.
