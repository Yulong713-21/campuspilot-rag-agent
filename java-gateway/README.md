# CampusPilot Java Gateway

这是可选的 Spring Boot 薄网关，不重写 Python Agent。适合未来接入 Java 用户系统、统一认证、
限流和审计；轻量本地演示只启动 FastAPI 即可。

## 运行

先启动 Python Agent：

```powershell
.\scripts\run_agent_api.ps1
```

再启动网关：

```powershell
cd java-gateway
mvn spring-boot:run
```

地址：

```text
GET  http://127.0.0.1:8080/gateway/health
POST http://127.0.0.1:8080/gateway/plans/generate
POST http://127.0.0.1:8080/gateway/programs/compare
```

Spring Boot 4.1.0 要求 Java 17 或更高版本。本机使用 Java 21 与 Maven 3.9.4。
