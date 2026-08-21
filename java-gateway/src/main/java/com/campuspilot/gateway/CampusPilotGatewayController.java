package com.campuspilot.gateway;

import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;

@RestController
@RequestMapping("/gateway")
public class CampusPilotGatewayController {

    private final RestClient agentClient;

    public CampusPilotGatewayController(
            @Value("${campuspilot.agent-base-url}") String agentBaseUrl) {
        this.agentClient = RestClient.builder().baseUrl(agentBaseUrl).build();
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of(
                "status", "ok",
                "service", "campuspilot-java-gateway");
    }

    @PostMapping(
            value = "/plans/generate",
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<?, ?> generatePlan(@RequestBody Map<String, Object> request) {
        return agentClient.post()
                .uri("/api/plans/generate")
                .contentType(MediaType.APPLICATION_JSON)
                .body(request)
                .retrieve()
                .body(Map.class);
    }

    @PostMapping(
            value = "/programs/compare",
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<?, ?> comparePrograms(@RequestBody Map<String, Object> request) {
        return agentClient.post()
                .uri("/api/programs/compare")
                .contentType(MediaType.APPLICATION_JSON)
                .body(request)
                .retrieve()
                .body(Map.class);
    }
}
