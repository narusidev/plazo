# Plazo

Lee tus entregas, fechas y notas del campus de CESUR (Moodle) y te avisa cuando un profesor mueve una fecha.

## Instalar

Descarga `Plazo.exe` de la última [Release](../../releases/latest) y ábrelo. Se copia a `%LOCALAPPDATA%\Programs\Plazo`, crea el acceso en el menú Inicio, arranca con Windows y se actualiza solo.

## Cómo funciona

- **Entrar:** una ventana de Plazo abre el campus y tú entras con Office 365. Plazo guarda la sesión cifrada con DPAPI y la mantiene viva mientras el PC está encendido. Si Microsoft te recuerda, la renueva sola sin pedirte el QR.
- **Qué lee:** cursos y calendario (con la API interna que usa la web del campus), lo pendiente de entregar (la agenda de acciones) y las notas (el informe de calificaciones). Todo de solo lectura.
- **Respaldo:** si la sesión caduca, las fechas siguen llegando por la URL privada del calendario iCal.
- **Avisos:** cambio de fecha, tarea nueva, nota publicada, y 48 h y 24 h antes de cada entrega pendiente.
- **Datos:** `%LOCALAPPDATA%\Plazo\plazo.db` (SQLite). El registro de errores está en `plazo.log`, en la misma carpeta.

## Publicar una versión nueva

1. Cambia `VERSION` en `version.py` y explica los cambios en `NOVEDADES.md`.
2. Sube los cambios a `main`. GitHub Actions pasa las pruebas, compila `Plazo.exe` en Windows y crea la Release.
3. Cada Plazo instalado la encuentra en menos de 6 horas, comprueba su SHA-256 y se sustituye.

## Código

| Archivo | Para qué |
|---|---|
| `plazo.py` | Arranque, proceso residente, servidor local de la interfaz |
| `login.py` | Ventana de inicio de sesión (WebView2) |
| `campus.py` | Peticiones al campus con la sesión e iCal |
| `sincronizar.py` | Detecta cambios y los guarda |
| `store.py` | Esquema SQLite |
| `actualizar.py` | Autoactualización desde Releases |
| `winsys.py` | Registro de Windows, avisos, ventana y cifrado DPAPI |
| `pruebas/` | Campus simulado y pruebas que se ejecutan en cada subida |
