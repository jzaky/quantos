# Netlify deployment

## Recommended: Git-connected deployment

The repository includes a root `netlify.toml` that tells Netlify to build the site from `/frontend`.

1. Push this repository to GitHub/GitLab/Bitbucket.
2. In Netlify, choose **Add new project > Import an existing project**.
3. Select the repository.
4. Netlify should read these settings automatically:
   - Base directory: `frontend`
   - Build command: `npm run build`
   - Publish directory: `out`
5. Deploy.

No backend URL is required for the visual demo. It automatically uses local simulated streaming data.

## Drag-and-drop deployment

Do not drag the source repository ZIP into Netlify Drop. Netlify Drop expects already-built website files.

Build first:

```bash
cd frontend
npm install
npm run build
```

Then drag the **contents of `frontend/out/`** into Netlify Drop, or upload the provided `quant-os-netlify-static.zip`.

## Optional live backend

Host the FastAPI backend separately and set this Netlify environment variable before building:

```text
NEXT_PUBLIC_QUANT_WS_URL=wss://YOUR-BACKEND/ws/stream
```

Without it, Quant OS stays in LOCAL SIM / paper-demo mode.
