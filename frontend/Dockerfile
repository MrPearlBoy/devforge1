# DevForge frontend — Vite dev server for the demo stack.
#
# For a production deployment build the static bundle (`npm run build`) and serve `dist/`
# from nginx or any static host; the dev server keeps hot reload for the demo.
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .

ENV HOST=0.0.0.0 \
    VITE_API_TARGET=http://api:8000

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
