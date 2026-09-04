package io.agentflow.api.controller;

import io.agentflow.api.dto.AttachmentResponse;
import io.agentflow.api.service.AttachmentService;
import io.agentflow.api.service.AttachmentService.LoadedAttachment;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/v1/attachments")
public class AttachmentsController {

    private final AttachmentService service;

    public AttachmentsController(AttachmentService service) {
        this.service = service;
    }

    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @ResponseStatus(HttpStatus.CREATED)
    public AttachmentResponse upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "caption", required = false) String caption) {
        return service.upload(file, caption);
    }

    @GetMapping("/{id}")
    public AttachmentResponse meta(@PathVariable String id) {
        return service.getMeta(id);
    }

    @GetMapping("/{id}/content")
    public ResponseEntity<byte[]> content(@PathVariable String id) {
        LoadedAttachment loaded = service.getContent(id);
        return ResponseEntity.ok()
                .header(
                        HttpHeaders.CONTENT_DISPOSITION,
                        "inline; filename=\"" + loaded.entity().getFilename() + "\"")
                .contentType(MediaType.parseMediaType(loaded.entity().getMediaType()))
                .body(loaded.data());
    }
}
