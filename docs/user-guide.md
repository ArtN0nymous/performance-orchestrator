# Guía de uso — performance-orchestrator

Guía paso a paso para configurar, validar, ejecutar y programar pruebas de rendimiento con esta plataforma.

Documentos relacionados: [configuración YAML](configuration.md) · [laboratorio local](local-development.md) · [despliegue](deployment.md) · [integración del target](target-integration.md) · [recuperación](recovery.md).

---

## 1. Qué es y qué no es

| Es | No es |
|----|--------|
| Un **orquestador reutilizable** que prepara el target, lanza **k6**, recolecta artefactos y limpia | Un conjunto de scripts k6 pegados a un solo cliente |
| Una app **Dockerizada** con CLI y scheduler **dentro** del contenedor | Dependencia del cron del host |
| Separación clara: **core** vs **overlay** del proyecto (YAML + scripts k6) | Un lugar para hardcodear IPs, usuarios o secretos en la imagen |

Flujo de cada ejecución:

```text
preflight → capturar estado → activar modo ventana (stub / maintenance)
→ verificar → ejecutar suite k6 → diagnósticos → desactivar modo ventana
→ verificar live → reporte HTML/JSON/MD/CSV
```

La limpieza corre siempre (`try/finally` + SIGINT/SIGTERM). Si el runner cae con el modo activo: `orchestrator recover <run-id>`.

---

## 2. Conceptos mínimos

| Concepto | Significado |
|----------|-------------|
| **Overlay** | Carpeta del proyecto con `orchestrator.yml` + scripts k6. El lab usa `examples/demo-project`. Un proyecto real es una carpeta externa (`ORCHESTRATOR_PROJECT_DIR`), no parte de este repo |
| **Suite** | Lista ordenada de tests (`smoke`, `weekend`, …) |
| **Test** | Un script k6 + parámetros (VUs, duración, thresholds) |
| **Target** | Servidor bajo prueba, administrado por SSH (`ssh_generic` o `laravel`) |
| **Modo ventana** | Lo que `enable_maintenance` activa en el target (p. ej. stub CRM, o flag de mantenimiento). No tiene que ser necesariamente `artisan down` |
| **run_id** | Identificador único de cada corrida; carpeta en `/data/results/<run-id>/` |

---

## 3. Requisitos

- Docker y Docker Compose
- Acceso SSH al target (usuario, clave privada, `known_hosts`)
- Overlay del proyecto montado en el contenedor como `/project`
- Volumen persistente en `/data` (SQLite + resultados)

Para el laboratorio local no hace falta un servidor real: el compose levanta un target con SSH.

---

## 4. Arranque rápido del laboratorio (validar la herramienta)

Úsalo para comprobar que el orquestador funciona; **no** sirve como benchmark de producción.

```bash
cd performance-orchestrator
cp .env.example .env

docker compose --profile local-target --profile observability up -d --build

docker compose exec orchestrator doctor
docker compose exec orchestrator list suites
docker compose exec orchestrator run --suite smoke
```

Puertos típicos en el host (pueden variar si hay conflicto):

| Servicio | Puerto |
|----------|--------|
| Target público | 18080 |
| Target de prueba | 18088 |
| SSH del target | 12222 |
| Grafana | 3000 |
| Prometheus | 9090 |
| InfluxDB | 8086 |

Informe: volumen `orchestrator-data` → `/data/results/<run-id>/report.html`.

```bash
docker compose exec orchestrator list runs
docker compose exec orchestrator report <run-id>
```

---

## 5. Configurar un proyecto real (paso a paso)

### Paso 1 — Copiar un overlay

```bash
cp -R test-definitions /ruta/a/mi-proyecto-overlay
# o: examples/demo-project  (solo lab)
```

Esa carpeta queda **fuera** de este repositorio. En `.env` apunta `ORCHESTRATOR_PROJECT_DIR` a ella. Para una API en otro compose: red compartida + `docker-compose.external-target.yml` (`make ext-up`). Ver [local-development.md](local-development.md).

No modifiques `src/orchestrator/` para adaptar un cliente.

### Paso 2 — Completar `orchestrator.yml`

Obligatorio revisar:

1. **`project.name` / `timezone`**
2. **`target.ssh`**: host, puerto, usuario, `identity_file`, `known_hosts_file`  
   - `strict_host_key_checking: "yes"` (nunca `no` por defecto)
3. **`target.commands`**: qué se ejecuta por SSH al activar/verificar/desactivar la ventana  
   - Ejemplo stub Laravel: poner `EXTERNAL_API_STUB_ENABLED=true|false` + `php artisan config:clear`
4. **`target.traffic`**:
   - `public_base_url` / `test_base_url`
   - `health_path`
   - Si la API **sigue en 200** durante la ventana (stub):  
     `public_expect_status_when_maintenance: 200` y `test_expect_status_when_maintenance: 200`
   - Si el público queda en **503**: URLs distintas o bypass real; k6 siempre usa `test_base_url`
5. **`suites` / `tests`**: scripts, VUs, duraciones, thresholds (sin valores de producción inventados en plantillas genéricas)
6. **`schedule`**: solo si usarás el scheduler (ver sección 8)
7. **`safety`**: techos de VUs, duración, error rate, CPU (si hay Prometheus)

Secretos vía variables de entorno:

```yaml
extra:
  API_KEY: ${API_ACCESS_KEY}
  ADMIN_API_KEY: ${API_ADMIN_ACCESS_KEY}
  ACCESS_TOKEN: ${STUB_ACCESS_TOKEN:-}
  ACCESS_TOKEN_HEADER: ${ACCESS_TOKEN_HEADER:-X-Access-Token}
```

### Paso 3 — Scripts k6

Estructura recomendada:

```text
mi-proyecto-overlay/
  orchestrator.yml
  k6/
    lib/          # helpers HTTP, options
    flows/        # secuencias de negocio reutilizables
    scenarios/    # smoke, baseline, load, …
    payments/     # solo sandbox / test keys
```

Reglas:

- No apuntes k6 al CRM externo.
- Pagos solo con credenciales de **prueba** en el servidor.
- Cabeceras y paths configurables por env, no marcas hardcodeadas en el core.

### Paso 4 — Montar el overlay en Docker

En `docker-compose.yml` (o override):

```yaml
services:
  orchestrator:
    environment:
      ORCHESTRATOR_CONFIG: /project/orchestrator.yml
      TARGET_SSH_HOST: tu-host
      # …resto de secrets vía env o Docker secrets
    volumes:
      - orchestrator-data:/data
      - /ruta/a/mi-proyecto-overlay:/project:ro
      - /ruta/segura/id_ed25519:/keys/id_ed25519:ro
```

La clave SSH se copia a `/data` con modo `600` al arrancar (ver entrypoint).  
`known_hosts` debe incluir la huella real del servidor (preferible generarla offline).

### Paso 5 — Validar antes de cargar

```bash
docker compose up -d orchestrator
docker compose exec orchestrator validate
docker compose exec orchestrator doctor
```

`doctor` comprueba: config, k6, ssh, curl, jq, directorio de datos, SSH al target, HTTP de salud, Prometheus/Influx si están habilitados, y si `DB_SNAPSHOT_ENABLED=true` valida `mysqldump`/`mysql` + conectividad DB en el objetivo.

Corrige fallos **antes** de programar jobs o lanzar load/stress.

### Paso 6 — Ejecución manual (one-shot)

```bash
docker compose exec orchestrator run --suite smoke
docker compose exec orchestrator run --suite weekend   # cuando la suite esté lista
docker compose exec orchestrator run --test health
```

Salida típica: JSON con `id`, `status`, `artifacts_dir`.  
Éxito esperado: `"status": "completed"`.

```bash
docker compose exec orchestrator status <run-id>
docker compose exec orchestrator report <run-id>
```

Artefactos en `/data/results/<run-id>/`:

- `report.html`, `summary.json`, `report.md`, `tests.csv`
- `timeline.jsonl`, `resolved-config.yml`, `manifest.json`
- `tests/<test-id>/` (summary k6, metrics, logs)
- `server/` (estado, diagnósticos, verify)

### Paso 7 — Recuperación

Si el estado es `recovery_required` o el proceso quedó con el stub/mantenimiento activo:

```bash
docker compose exec orchestrator recover <run-id>
```

Luego confirma en el servidor (SSH o health) que el flag de stub / mantenimiento quedó **apagado**.

---

## 6. Checklist operativo antes de una ventana real

- [ ] Overlay validado (`validate` + `doctor` OK)
- [ ] Modo stub / prueba desplegado en la API y ensayado
- [ ] Claves de pago en modo test en el servidor
- [ ] Límite de rate limit elevado si la suite supera el techo habitual
- [ ] Respaldo de base de datos acordado
- [ ] Comunicación a stakeholders (CRM simulado / posible impacto)
- [ ] Monitoreo (Prometheus u observación acordada) listo
- [ ] `known_hosts` e identity correctos (no la clave del lab)
- [ ] Suite smoke manual OK contra el target real
- [ ] Plan de revert: stub off, Stripe live, rate limit normal

---

## 7. CLI de referencia

| Comando | Uso |
|---------|-----|
| `orchestrator validate` | Valida el YAML |
| `orchestrator doctor` | Diagnóstico de dependencias y target |
| `orchestrator list suites` | Suites definidas |
| `orchestrator list runs` | Historial en SQLite |
| `orchestrator run --suite <id>` | Ejecuta una suite |
| `orchestrator run --test <id>` | Ejecuta un solo test |
| `orchestrator status <run-id>` | Estado del run |
| `orchestrator report <run-id>` | Ruta del informe HTML |
| `orchestrator recover <run-id>` | Desactiva ventana y verifica live |
| `orchestrator scheduler` | Bucle persistente de jobs (default del contenedor) |

Opciones globales:

```bash
orchestrator --config /project/orchestrator.yml …
# o: ORCHESTRATOR_CONFIG=/project/orchestrator.yml
```

---

## 8. Programar ejecuciones automáticas (scheduler)

El contenedor arranca por defecto en modo **scheduler** (no usa cron del host).

En el overlay:

```yaml
schedule:
  timezone: America/Mexico_City   # IANA
  misfire_grace_seconds: 300
  tick_seconds: 5
  jobs:
    - id: weekend-capacity
      cron: "0 10 * * 6"          # sábados 10:00
      suite: weekend
      misfire: skip               # o: run
      enabled: true
```

Comportamiento:

- Persistencia en SQLite (último disparo, evita duplicados)
- Un solo run a la vez (`max_concurrent_runs: 1`)
- Política de *misfire* explícita: `skip` o `run`
- En cada tick también intenta recuperar ventanas con TTL vencido

Arranque:

```bash
docker compose up -d   # profiles según necesites (observability, etc.)
# el proceso orchestrator queda en: orchestrator scheduler
```

Después del fin de semana (o del job):

```bash
docker compose exec orchestrator list runs
docker compose exec orchestrator report <run-id>
# abrir report.html y, si aplica, Grafana
```

---

## 9. Profiles de Compose

| Profile | Qué levanta |
|---------|-------------|
| *(default)* | `orchestrator` (scheduler) |
| `local-target` | nginx + app fixture + db + payment-mock |
| `observability` | Prometheus, InfluxDB, Grafana, cAdvisor |
| `chaos` | Toxiproxy (opcional) |

```bash
docker compose --profile local-target --profile observability up -d --build
```

---

## 10. Problemas frecuentes

| Síntoma | Qué revisar |
|---------|-------------|
| `doctor` falla en SSH | Identity, `known_hosts`, usuario, puerto, red Docker |
| `public traffic not in expected maintenance state` | Flag stub / maintenance no se aplicó, o `public_expect_*` no coincide |
| k6 solo ve 503 | Estás golpeando la URL pública en maintenance; usa `test_base_url` o bypass real |
| `another run is in progress` | Hay un run activo o un lock; `list runs` / esperar / recover |
| `recovery_required` | `recover <run-id>` y verificar stub off en el servidor |
| Rate limit / muchos 429 | Subir throttle de la API para la ventana |
| Influx sin datos | Extensión xk6 puede no estar; los JSON/HTML locales siguen siendo la fuente de verdad |

---

## 11. Dónde seguir

1. Laboratorio: esta guía §4 + [local-development.md](local-development.md)  
2. Overlay de un proyecto: carpeta externa en `ORCHESTRATOR_PROJECT_DIR` (plantilla: `test-definitions/`)  
3. YAML detallado: [configuration.md](configuration.md)  
4. Producción / secretos: [deployment.md](deployment.md), [security.md](security.md)  
5. Estado de implementación: [../IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md)
