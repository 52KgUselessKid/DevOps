FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 mvn -B -q -DskipTests package org.apache.maven.plugins:maven-dependency-plugin:3.8.1:copy-dependencies

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /build/target/backend-lab1-1.0.0.jar ./app.jar
COPY --from=build /build/target/dependency ./lib
USER 10001:10001
ENTRYPOINT ["java", "-cp", "/app/app.jar:/app/lib/*", "com.gameshelf.lab1.Main"]
