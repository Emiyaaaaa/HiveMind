package io.agentflow.api.controller;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import io.agentflow.api.config.AgentflowProperties;
import io.agentflow.api.config.JacksonConfig;
import io.agentflow.api.config.PropertiesConfig;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(controllers = HealthController.class)
@Import({JacksonConfig.class, PropertiesConfig.class, AgentflowProperties.class})
@TestPropertySource(properties = {
        "agentflow.version=0.1.0",
        "agentflow.adapters=echo,langgraph",
})
class HealthControllerTest {

    @Autowired
    MockMvc mvc;

    @Test
    void healthEndpointReturnsStatusAndAdapters() throws Exception {
        mvc.perform(get("/v1/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("ok"))
                .andExpect(jsonPath("$.version").value("0.1.0"))
                .andExpect(jsonPath("$.adapters[0]").value("echo"))
                .andExpect(jsonPath("$.adapters[1]").value("langgraph"));
    }
}
