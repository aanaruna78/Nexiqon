<?php
/**
 * Plugin Name: Nexiqon Chat
 * Description: Adds the Nexiqon assistant to your site. Use the [nexiqon_chat] shortcode for an inline chat, or turn on the floating button in Settings > Nexiqon Chat.
 * Version: 0.1.0
 * License: Apache-2.0
 */

if (!defined('ABSPATH')) {
    exit;
}

function nexiqon_chat_options() {
    return wp_parse_args(get_option('nexiqon_chat', array()), array(
        'script' => '',   // https://<studio>/widget/nexiqon-chat.js
        'gateway' => '',  // https://<gateway>
        'agent' => '',
        'key' => '',      // widget key (public; only works from the sites it was issued for)
        'floating' => '0',
    ));
}

function nexiqon_chat_tag($attrs) {
    $o = nexiqon_chat_options();
    $a = shortcode_atts(array(
        'agent' => $o['agent'],
        'locale' => substr(get_locale(), 0, 2),
        'mode' => 'inline',
        'theme' => 'auto',
    ), $attrs, 'nexiqon_chat');
    return sprintf(
        '<nexiqon-chat agent="%s" api-base="%s" api-key="%s" locale="%s" mode="%s" theme="%s"></nexiqon-chat>',
        esc_attr($a['agent']), esc_url($o['gateway']), esc_attr($o['key']),
        esc_attr($a['locale']), esc_attr($a['mode']), esc_attr($a['theme'])
    );
}

add_action('wp_enqueue_scripts', function () {
    $o = nexiqon_chat_options();
    if ($o['script']) {
        wp_enqueue_script('nexiqon-chat', esc_url($o['script']), array(), null, array('in_footer' => true));
    }
});

// <script type="module"> is required: the widget is an ES module.
add_filter('script_loader_tag', function ($tag, $handle) {
    return $handle === 'nexiqon-chat' ? str_replace('<script ', '<script type="module" ', $tag) : $tag;
}, 10, 2);

add_shortcode('nexiqon_chat', 'nexiqon_chat_tag');

add_action('wp_footer', function () {
    $o = nexiqon_chat_options();
    if ($o['floating'] === '1') {
        echo nexiqon_chat_tag(array('mode' => 'floating')); // phpcs:ignore -- attributes escaped above
    }
});

add_action('admin_menu', function () {
    add_options_page('Nexiqon Chat', 'Nexiqon Chat', 'manage_options', 'nexiqon-chat', function () {
        $o = nexiqon_chat_options();
        echo '<div class="wrap"><h1>Nexiqon Chat</h1><form method="post" action="options.php">';
        settings_fields('nexiqon_chat');
        foreach (array('script' => 'Widget script URL', 'gateway' => 'Gateway URL', 'agent' => 'Assistant', 'key' => 'Widget key') as $k => $label) {
            printf('<p><label>%s<br><input class="regular-text" name="nexiqon_chat[%s]" value="%s"></label></p>', esc_html($label), esc_attr($k), esc_attr($o[$k]));
        }
        printf('<p><label><input type="checkbox" name="nexiqon_chat[floating]" value="1" %s> Show the floating chat button on every page</label></p>', checked($o['floating'], '1', false));
        submit_button();
        echo '</form></div>';
    });
});

add_action('admin_init', function () {
    register_setting('nexiqon_chat', 'nexiqon_chat', array('sanitize_callback' => function ($v) {
        return array(
            'script' => esc_url_raw($v['script'] ?? ''),
            'gateway' => esc_url_raw($v['gateway'] ?? ''),
            'agent' => sanitize_key($v['agent'] ?? ''),
            'key' => sanitize_text_field($v['key'] ?? ''),
            'floating' => empty($v['floating']) ? '0' : '1',
        );
    }));
});
