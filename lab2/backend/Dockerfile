# Digest фиксирует базу сборки, даже если тег позже изменится.
FROM maven:3.9-eclipse-temurin-21@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320 AS build
WORKDIR /build
# Зависимости меняются реже кода, поэтому этот слой идёт первым.
COPY pom.xml .
RUN mvn -B -q -DskipTests dependency:go-offline dependency:copy-dependencies
COPY src ./src
RUN mvn -B -q -o -DskipTests package

FROM eclipse-temurin:21.0.9_10-jre-alpine@sha256:08eecc477dbe3f2e33daac27f36e41daf7f4ec51d2f3396006e54fa41832c74c
WORKDIR /app
RUN addgroup -S shelf && adduser -S -G shelf shelf
# В runtime переносим только приложение и JDBC-драйвер, без Maven и исходников.
COPY --from=build --chown=shelf:shelf /build/target/backend-lab2-1.0.0.jar ./app.jar
COPY --from=build --chown=shelf:shelf /build/target/dependency ./lib
ENV HOST=0.0.0.0 PORT=8080 JAVA_TOOL_OPTIONS="-Xms16m -Xmx192m -XX:ActiveProcessorCount=2"
USER shelf
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=15s --retries=6 CMD wget -q -O /dev/null http://127.0.0.1:8080/health || exit 1
ENTRYPOINT ["java", "-cp", "/app/app.jar:/app/lib/*", "com.gameshelf.lab2.Main"]
