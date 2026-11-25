# Auto-push de commits

El repositorio incluye el hook versionado `.githooks/post-commit`. Git **no**
activa los hooks de un directorio alternativo automáticamente al clonar: hay
que registrar `core.hooksPath` una vez por clon.

## Activar en un clon nuevo

Desde la raíz del repositorio:

```bash
git config --local core.hooksPath .githooks
```

En Linux/macOS, si el archivo no conserva el bit de ejecución:

```bash
chmod +x .githooks/post-commit
```

En Windows basta con Git Bash o Git for Windows; el modo ejecutable ya está
registrado en el repositorio. Para comprobar la activación:

```bash
git config --get core.hooksPath
# .githooks
```

## Qué hace

- Se ejecuta después de cada commit.
- Solo actúa en la rama `main`.
- Empuja `HEAD` a `origin/main` sin hacer `force`, sin stage, sin amend y sin
  tocar archivos de datos.
- Si el push falla, el commit local se conserva y el error queda en
  `.git/auto-push.log`.
- Usa la configuración SSH/HTTPS existente del clon, en modo no interactivo.
- Evita dos pushes simultáneos con `.git/auto-push.lock`.

## Desactivarlo

Para un commit local sin auto-push:

```bash
GIT_AUTO_PUSH=0 git commit -m "mensaje"
```

En PowerShell:

```powershell
$env:GIT_AUTO_PUSH="0"; git commit -m "mensaje"; Remove-Item Env:GIT_AUTO_PUSH
```

Para desactivarlo en todo el clon:

```bash
git config --local --unset core.hooksPath
```

El hook no modifica el bot, la configuración del 8765 ni la base de datos; solo
ejecuta `git push`.
