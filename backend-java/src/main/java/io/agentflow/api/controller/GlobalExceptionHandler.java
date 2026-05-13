package io.agentflow.api.controller;

import io.agentflow.api.service.AgentNameConflictException;
import io.agentflow.api.service.AgentNotFoundException;
import io.agentflow.api.service.RunNotFoundException;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * Match FastAPI's {@code {"detail": "..."}} error body shape so the frontend
 * does not have to special-case Java responses.
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(AgentNotFoundException.class)
    public ResponseEntity<Map<String, String>> handleAgentNotFound(AgentNotFoundException ex) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("detail", ex.getMessage()));
    }

    @ExceptionHandler(RunNotFoundException.class)
    public ResponseEntity<Map<String, String>> handleRunNotFound(RunNotFoundException ex) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("detail", ex.getMessage()));
    }

    @ExceptionHandler(AgentNameConflictException.class)
    public ResponseEntity<Map<String, String>> handleConflict(AgentNameConflictException ex) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("detail", ex.getMessage()));
    }
}
