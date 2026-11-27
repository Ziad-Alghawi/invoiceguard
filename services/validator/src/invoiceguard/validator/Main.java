package invoiceguard.validator;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import de.kosit.validationtool.cmd.CommandLineApplication;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.Executors;
import javax.xml.XMLConstants;
import javax.xml.parsers.ParserConfigurationException;
import javax.xml.parsers.SAXParserFactory;
import javax.xml.transform.sax.SAXSource;
import javax.xml.transform.stream.StreamSource;
import net.sf.saxon.s9api.Processor;
import net.sf.saxon.s9api.QName;
import net.sf.saxon.s9api.SaxonApiException;
import net.sf.saxon.s9api.Serializer;
import net.sf.saxon.s9api.XdmAtomicValue;
import net.sf.saxon.s9api.XdmDestination;
import net.sf.saxon.s9api.XdmNode;
import net.sf.saxon.s9api.XdmNodeKind;
import net.sf.saxon.s9api.XsltCompiler;
import net.sf.saxon.s9api.XsltExecutable;
import org.xml.sax.InputSource;
import org.xml.sax.SAXException;
import org.xml.sax.XMLReader;

/**
 * Starts the official KoSIT validator daemon unchanged (its arguments, port 8080) and, in the same
 * JVM, the KoSIT XRechnung visualization (ADR-029) on a second port.
 *
 * <p>POST UBL or CII invoice XML to {@code /visualize?lang=de} (or {@code en}) and get the HTML
 * view: 200 HTML, 415 not an invoice the visualization knows, 413 too large, 422 unreadable XML.
 * {@code GET /health} answers 200. The stylesheets are compiled once at start with the Saxon
 * that the validator jar already contains, so no second JVM and no new pod are needed.
 */
public final class Main {
    private static final int MAX_BYTES = 10 * 1024 * 1024;
    private static final String UBL_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2";
    private static final String UBL_CREDIT_NOTE =
            "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2";
    private static final String CII = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100";

    private final Processor processor = new Processor(false);
    private final Map<String, XsltExecutable> toXr;
    private final XsltExecutable toHtml;

    private Main(Path stylesheets) throws SaxonApiException {
        XsltCompiler compiler = processor.newXsltCompiler();
        toXr = Map.of(
                UBL_INVOICE, compile(compiler, stylesheets.resolve("ubl-invoice-xr.xsl")),
                UBL_CREDIT_NOTE, compile(compiler, stylesheets.resolve("ubl-creditnote-xr.xsl")),
                CII, compile(compiler, stylesheets.resolve("cii-xr.xsl")));
        toHtml = compile(compiler, stylesheets.resolve("xrechnung-html.xsl"));
    }

    private static XsltExecutable compile(XsltCompiler compiler, Path stylesheet)
            throws SaxonApiException {
        return compiler.compile(new StreamSource(stylesheet.toFile()));
    }

    /** A namespace-aware parser that refuses DTDs, so no external entity is ever read (XXE). */
    private static XMLReader safeReader() throws ParserConfigurationException, SAXException {
        SAXParserFactory factory = SAXParserFactory.newInstance();
        factory.setNamespaceAware(true);
        factory.setXIncludeAware(false);
        factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
        factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
        return factory.newSAXParser().getXMLReader();
    }

    private static String rootNamespace(XdmNode document) {
        for (XdmNode child : document.children()) {
            if (child.getNodeKind() == XdmNodeKind.ELEMENT) {
                return child.getNodeName().getNamespace();
            }
        }
        return "";
    }

    /** The invoice as HTML in the given language, or null when it is no UBL or CII invoice. */
    byte[] visualize(byte[] xml, String lang)
            throws SaxonApiException, ParserConfigurationException, SAXException {
        XdmNode invoice = processor.newDocumentBuilder()
                .build(new SAXSource(safeReader(), new InputSource(new ByteArrayInputStream(xml))));
        XsltExecutable first = toXr.get(rootNamespace(invoice));
        if (first == null) {
            return null;
        }
        XdmDestination xr = new XdmDestination();
        first.load30().applyTemplates(invoice, xr);
        ByteArrayOutputStream html = new ByteArrayOutputStream();
        Serializer serializer = processor.newSerializer(html);
        var transformer = toHtml.load30();
        transformer.setStylesheetParameters(Map.of(new QName("lang"), new XdmAtomicValue(lang)));
        transformer.applyTemplates(xr.getXdmNode(), serializer);
        return html.toByteArray();
    }

    private static byte[] readLimited(InputStream body) throws IOException {
        byte[] content = body.readNBytes(MAX_BYTES + 1);
        return content.length > MAX_BYTES ? null : content;
    }

    private static void respond(HttpExchange exchange, int status, String type, byte[] body)
            throws IOException {
        exchange.getResponseHeaders().set("Content-Type", type);
        exchange.sendResponseHeaders(status, body.length);
        try (var out = exchange.getResponseBody()) {
            out.write(body);
        }
    }

    private static void text(HttpExchange exchange, int status, String message) throws IOException {
        respond(exchange, status, "text/plain; charset=utf-8", message.getBytes(StandardCharsets.UTF_8));
    }

    private void handle(HttpExchange exchange) throws IOException {
        try (exchange) {
            if (!"POST".equals(exchange.getRequestMethod())) {
                text(exchange, 405, "POST the invoice XML.");
                return;
            }
            String query = exchange.getRequestURI().getQuery();
            String lang = "lang=en".equals(query) ? "en" : "de";
            byte[] xml = readLimited(exchange.getRequestBody());
            if (xml == null) {
                text(exchange, 413, "The invoice is larger than 10 MiB.");
                return;
            }
            byte[] html;
            try {
                html = visualize(xml, lang);
            } catch (SaxonApiException | SAXException | ParserConfigurationException error) {
                text(exchange, 422, "The invoice XML cannot be visualized.");
                return;
            }
            if (html == null) {
                text(exchange, 415, "Not a UBL or CII invoice.");
                return;
            }
            respond(exchange, 200, "text/html; charset=utf-8", html);
        }
    }

    public static void main(String[] args) throws Exception {
        Path stylesheets = Path.of(System.getenv().getOrDefault(
                "VISUALIZATION_STYLESHEETS", "/opt/kosit/visualization/xsl"));
        int port = Integer.parseInt(System.getenv().getOrDefault("VISUALIZATION_PORT", "8082"));
        Main main = new Main(stylesheets);
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 0);
        server.createContext("/visualize", main::handle);
        server.createContext("/health", exchange -> {
            try (exchange) {
                text(exchange, 200, "UP");
            }
        });
        // Two at a time: the view is opened by a reviewer, not in bulk; the validator keeps its own.
        server.setExecutor(Executors.newFixedThreadPool(2));
        server.start();
        CommandLineApplication.main(args);
    }
}
