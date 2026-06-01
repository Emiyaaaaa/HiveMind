package io.agentflow.api.observability;

import io.agentflow.api.config.AgentflowProperties;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.concurrent.TimeUnit;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Records RED metrics aligned with the Python FastAPI middleware
 * ({@code agentflow.http.server.*}).
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
@ConditionalOnProperty(prefix = "agentflow.otel", name = "enabled", havingValue = "true")
public class RedMetricsFilter extends OncePerRequestFilter {

    private final Counter httpRequests;
    private final Counter httpErrors;
    private final Timer httpDuration;

    public RedMetricsFilter(MeterRegistry registry, AgentflowProperties props) {
        String service = props.getOtel().getServiceName();
        httpRequests = Counter.builder("agentflow.http.server.requests")
                .description("HTTP requests (rate)")
                .tag("service", service)
                .register(registry);
        httpErrors = Counter.builder("agentflow.http.server.errors")
                .description("HTTP server errors")
                .tag("service", service)
                .register(registry);
        httpDuration = Timer.builder("agentflow.http.server.duration")
                .description("HTTP request duration")
                .tag("service", service)
                .publishPercentileHistogram()
                .register(registry);
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        long start = System.nanoTime();
        int status = 500;
        try {
            filterChain.doFilter(request, response);
            status = response.getStatus();
        } finally {
            String route = resolveRoute(request);
            httpRequests.increment();
            httpDuration.record(System.nanoTime() - start, TimeUnit.NANOSECONDS);
            if (status >= 500) {
                httpErrors.increment();
            }
        }
    }

    private static String resolveRoute(HttpServletRequest request) {
        Object pattern = request.getAttribute(
                "org.springframework.web.servlet.HandlerMapping.bestMatchingPattern");
        if (pattern != null) {
            return pattern.toString();
        }
        return request.getRequestURI();
    }
}
