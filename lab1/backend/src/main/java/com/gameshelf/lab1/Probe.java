package com.gameshelf.lab1;

import java.net.URI;
import java.net.HttpURLConnection;

/** Docker проверяет не только порт, но и чтение базы через API. */
public class Probe {
    public static void main(String[] args) throws Exception {
        var connection = (HttpURLConnection) URI.create(args[0]).toURL().openConnection();
        connection.setConnectTimeout(1500);
        connection.setReadTimeout(1500);
        try { if (connection.getResponseCode() != 200) System.exit(1); }
        finally { connection.disconnect(); }
    }
}
