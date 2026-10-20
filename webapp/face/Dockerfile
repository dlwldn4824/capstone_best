# 단독 배포(Cloud Run, 포트 8080): 앱은 /face/, 캐릭터 · 글꼴은 /assets/ 에 둔다. / 는 /face/ 로 보낸다.
# 업로드 전에 npm run deploy(predeploy)가 shared-assets/ 사본을 채운다. 저장소 밖(../../assets)은 빌드 컨텍스트에 없다.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html/face
COPY --from=build /app/shared-assets /usr/share/nginx/html/assets
RUN chmod -R a+rX /usr/share/nginx/html
EXPOSE 8080
