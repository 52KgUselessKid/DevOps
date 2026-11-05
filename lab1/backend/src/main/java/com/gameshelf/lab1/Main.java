package com.gameshelf.lab1;

import com.sun.net.httpserver.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.sql.*;
import java.util.*;
import java.util.concurrent.Executors;

/** Наша полка: Java принимает запросы, а игры живут в отдельном PostgreSQL. */
public class Main {
    static String env(String name, String fallback) { return System.getenv().getOrDefault(name, fallback); }
    // Настройки берём из окружения; для локального запуска уже есть значения по умолчанию.
    static Connection db() throws SQLException {
        return DriverManager.getConnection(env("DB_URL", "jdbc:postgresql://127.0.0.1:5432/games"),
                env("DB_USER", "gamer"), env("DB_PASSWORD", "gamer_local"));
    }
    public static void main(String[] args) throws Exception {
        // При первом запуске создаём таблицу, а при следующих оставляем её и игры как есть.
        try (var c = db(); var s = c.createStatement()) {
            s.execute("""
                CREATE TABLE IF NOT EXISTS games (
                  id BIGSERIAL PRIMARY KEY,
                  title VARCHAR(120) NOT NULL CHECK (length(trim(title)) > 0),
                  platform VARCHAR(60) NOT NULL CHECK (length(trim(platform)) > 0),
                  status VARCHAR(20) NOT NULL CHECK (status IN ('planned','playing','completed')),
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """);
        }
        log("[DB] PostgreSQL connected; games table ready");
        var server = HttpServer.create(new InetSocketAddress(env("HOST", "127.0.0.1"), Integer.parseInt(env("PORT", "8080"))), 0);
        // Один сервер отдаёт и страницу, и API - браузеру достаточно одного адреса.
        server.createContext("/api/games", Main::games);
        server.createContext("/", e -> {
            send(e,404,"application/json","{\"error\":\"Use /api/games; nginx serves the frontend\"}");
            e.close();
        });
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        Runtime.getRuntime().addShutdownHook(new Thread(() -> server.stop(1)));
        server.start();
        System.out.println("Game Shelf: http://" + env("HOST","127.0.0.1") + ":" + server.getAddress().getPort());
        log("[HTTP] Server started; waiting for requests");
    }
    static void games(HttpExchange e) throws java.io.IOException {
        try {
            if (!e.getRequestURI().getPath().equals("/api/games")) { send(e,404,"application/json","{\"error\":\"Not found\"}"); return; }
            if (e.getRequestMethod().equals("GET")) {
                // Каждый раз читаем настоящую таблицу, поэтому после F5 записи остаются.
                var out = new StringJoiner(",", "[", "]");
                int count = 0;
                try (var c=db(); var s=c.prepareStatement("SELECT id,title,platform,status FROM games ORDER BY id DESC"); var r=s.executeQuery()) {
                    while(r.next()) {
                        count++;
                        out.add("{\"id\":"+r.getLong(1)+",\"title\":"+json(r.getString(2))+",\"platform\":"+json(r.getString(3))+",\"status\":"+json(r.getString(4))+"}");
                    }
                }
                log("[DB] Read games: " + count);
                send(e,200,"application/json",out.toString());
            } else if(e.getRequestMethod().equals("POST")) {
                if (!e.getRequestHeaders().getFirst("Content-Type").toLowerCase(Locale.ROOT).startsWith("application/x-www-form-urlencoded")) {
                    send(e,415,"application/json","{\"error\":\"Ожидается форма application/x-www-form-urlencoded\"}");return;
                }
                // Для маленькой формы хватит 8 КБ; большие запросы сразу отклоняем.
                byte[] bytes=e.getRequestBody().readNBytes(8193);
                if(bytes.length>8192) {send(e,413,"application/json","{\"error\":\"Слишком большая форма\"}");return;}
                Map<String,String> form=new HashMap<>();
                for(String part:new String(bytes,StandardCharsets.UTF_8).split("&")) {
                    String[] kv=part.split("=",2);
                    if(kv.length==2) form.put(URLDecoder.decode(kv[0],StandardCharsets.UTF_8),URLDecoder.decode(kv[1],StandardCharsets.UTF_8));
                }
                String title=form.getOrDefault("title", "").strip(), platform=form.getOrDefault("platform", "").strip(), status=form.getOrDefault("status", "planned");
                // Форму можно отправить и без браузера, поэтому проверяем её и здесь.
                if(title.isEmpty() || title.length()>120 || platform.isEmpty() || platform.length()>60 || !Set.of("planned","playing","completed").contains(status)) {
                    send(e,400,"application/json","{\"error\":\"Проверь название, платформу и статус игры\"}");return;
                }
                // Знаки ? - места для данных: название игры не станет частью SQL-команды.
                try(var c=db(); var s=c.prepareStatement("INSERT INTO games(title,platform,status) VALUES (?,?,?) RETURNING id")) {
                    s.setString(1,title);s.setString(2,platform);s.setString(3,status);
                    long id;
                    try(var r=s.executeQuery()){r.next();id=r.getLong(1);}
                    log("[DB] Saved game id=" + id);
                    send(e,201,"application/json","{\"id\":"+id+"}");
                }
            } else {e.getResponseHeaders().set("Allow","GET, POST");send(e,405,"application/json","{\"error\":\"Method not allowed\"}");}
        } catch(SQLException ex) {
            System.err.println("Database request failed: " + ex.getSQLState());
            send(e,503,"application/json","{\"error\":\"База временно недоступна. Попробуй ещё раз\"}");
        } catch(IllegalArgumentException | NullPointerException ex) {
            send(e,400,"application/json","{\"error\":\"Некорректная форма\"}");
        } finally {e.close();}
    }
    // Кавычки и переносы в названии не должны ломать JSON-ответ.
    static String json(String s) {
        var out=new StringBuilder("\"");
        for(char ch:s.toCharArray()) {
            switch(ch) {case '"' -> out.append("\\\"");case '\\' -> out.append("\\\\");default -> {if(ch<32) out.append(String.format("\\u%04x",(int)ch));else out.append(ch);}}
        }
        return out.append('"').toString();
    }
    // В консоли видно, что запрос дошёл до сервера и чем он закончился.
    static void log(String message) {
        System.out.println(java.time.LocalTime.now().withNano(0) + " [" + env("INSTANCE_ID", "backend-local") + "] " + message);
    }
    static void send(HttpExchange e,int status,String type,String text) throws java.io.IOException {
        byte[] body=text.getBytes(StandardCharsets.UTF_8);
        // Идентификатор ставит сам Java-сервер, nginx только передаёт его браузеру.
        e.getResponseHeaders().set("X-Backend-Id", env("INSTANCE_ID", "backend-local"));
        e.getResponseHeaders().set("Content-Type",type+"; charset=utf-8");
        e.getResponseHeaders().set("Cache-Control","no-store");
        e.getResponseHeaders().set("X-Content-Type-Options","nosniff");
        e.sendResponseHeaders(status,body.length);
        try(var out=e.getResponseBody()){out.write(body);}
        log("[HTTP] " + e.getRequestMethod() + " " + e.getRequestURI().getRawPath() + " -> " + status);
    }
}
