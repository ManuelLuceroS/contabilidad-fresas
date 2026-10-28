(() => {
  document.querySelectorAll('#share-receipt, [data-share-file]').forEach(button => {
  const status = document.getElementById(button.dataset.statusId || 'receipt-share-status');
  let pdfPromise;
  function prepare() {
    // Se genera desde la venta guardada; la URL sigue exigiendo sesión y permisos.
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
      if (navigator.canShare?.({files: [file]})) {
        await navigator.share({files: [file], title: button.dataset.filename, text: 'Comprobante de venta'});
        status.textContent = 'Se cerró el diálogo para compartir. Comprueba el envío en la aplicación elegida.';
      } else {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url; link.download = file.name; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        status.textContent = 'PDF descargado. Abre la conversación de WhatsApp y adjunta el archivo descargado. Aún no se ha enviado.';
      }
    } catch (error) {
      if (error.name !== 'AbortError') {
        status.textContent = 'No se pudo compartir. Descarga el PDF y adjúntalo en WhatsApp.';
        pdfPromise = prepare(); pdfPromise.catch(() => {});
      }
    } finally { button.disabled = false; }
  });
  });
})();
