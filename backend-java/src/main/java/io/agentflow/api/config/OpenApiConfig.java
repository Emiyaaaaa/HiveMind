package io.agentflow.api.config;

import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.info.License;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {

    private static final String API_KEY_SCHEME = "ApiKeyAuth";
    private static final String BEARER_SCHEME = "BearerAuth";

    @Bean
    public OpenAPI agentflowOpenApi(AgentflowProperties properties) {
        return new OpenAPI()
                .info(new Info()
                        .title("AgentFlow API")
                        .version(properties.getVersion())
                        .description(
                                "HTTP surface for AgentFlow runs, agents, and streaming events. "
                                        + "See docs/api-contract.md for behavioral notes.")
                        .contact(new Contact().name("AgentFlow").url("https://github.com/hivemind/agentflow"))
                        .license(new License().name("Apache 2.0")))
                .components(new Components()
                        .addSecuritySchemes(
                                API_KEY_SCHEME,
                                new SecurityScheme()
                                        .type(SecurityScheme.Type.APIKEY)
                                        .in(SecurityScheme.In.HEADER)
                                        .name("X-Api-Key")
                                        .description("Tenant-scoped API key (also accepted as Bearer token)."))
                        .addSecuritySchemes(
                                BEARER_SCHEME,
                                new SecurityScheme()
                                        .type(SecurityScheme.Type.HTTP)
                                        .scheme("bearer")
                                        .bearerFormat("JWT or API key")
                                        .description("OIDC JWT or API key in Authorization header.")))
                .addSecurityItem(new SecurityRequirement().addList(API_KEY_SCHEME))
                .addSecurityItem(new SecurityRequirement().addList(BEARER_SCHEME));
    }
}
