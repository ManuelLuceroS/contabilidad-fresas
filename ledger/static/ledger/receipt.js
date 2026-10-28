(() => {
  document.querySelectorAll('#share-receipt, [data-share-file]').forEach(button => {
    const status = document.getElementById(button.dataset.statusId || 'receipt-share-status');
    let pdfPromise;
    function prepare() {
      // El PDF privado se obtiene de la operación guardada, sin volver a diligenciarla.
      return fetch(button.dataset.pdf, {credentials: 'same-origin'}).then(response => {
        if (!response.ok || !response.headers.get('Content-Type')?.includes('application/pdf')) throw new Error('No se pudo generar el PDF.');
        return response.blob();
      });
    }
    pdfPromise = prepare();
    pdfPromise.catch(() => { status.textContent = 'Usa Descargar PDF para obtener el comprobante o vuelve a intentar compartir.'; });
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const blob = await pdfPromise;
        const file = new File([blob], button.dataset.filename, {type: 'application/pdf'});
        const payload = {files: [file], title: button.dataset.filename, text: button.dataset.shareText || 'Comprobante adjunto'};
        if (navigator.canShare?.(payload)) {
          await navigator.share(payload);
          status.textContent = 'Comprueba en WhatsApp el contacto, el PDF y el mensaje con el total. Si el texto no aparece, cópialo y pégalo en el chat.';
        } else {
          const url = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = url; link.download = file.name; link.click();
          setTimeout(() => URL.revokeObjectURL(url), 60000);
          status.textContent = 'PDF descargado. Pulsa Abrir WhatsApp con el total y adjunta el archivo descargado. Aún no se ha enviado.';
        }
      } catch (error) {
        if (error.name === 'AbortError') {
          status.textContent = 'Se canceló el diálogo. Puedes volver a compartir el PDF y el total.';
        } else {
          status.textContent = 'No se pudo compartir. Descarga el PDF, copia el mensaje con el total y adjúntalo en WhatsApp.';
          pdfPromise = prepare(); pdfPromise.catch(() => {});
        }
      } finally { button.disabled = false; }
    });
  });
  document.querySelectorAll('[data-copy-message]').forEach(button => {
    button.addEventListener('click', async () => {
      const field = document.getElementById(button.dataset.copyMessage);
      const status = document.getElementById(button.dataset.statusId);
      try {
        await navigator.clipboard.writeText(field.value);
        status.textContent = 'Mensaje con el total copiado. Pégalo en WhatsApp junto al PDF.';
      } catch {
        field.focus(); field.select();
        status.textContent = 'Mensaje seleccionado. Cópialo y pégalo en WhatsApp junto al PDF.';
      }
    });
  });
})();
