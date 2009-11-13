# -*- coding: utf-8 -*-
"""
    pygments.lexers.sp4
    ~~~~~~~~~~~~~~~~~~~~~

    Lexer for CustIS m4-preprocessed PL/SQL.

    :copyright: 2009+ by Vitaliy Filippov <vitalif@mail.ru>.
    :license: BSD, see LICENSE for more details.
,
    'Sp4Lexer': ('pygments.lexers.sp4', 'SP4', ('sp4',), ('*.sp4'), ('text/x-sp4',))
"""

import re

from pygments.lexer import Lexer, RegexLexer, include, bygroups, using, this, \
                           do_insertions
from pygments.token import Error, Punctuation, \
     Text, Comment, Operator, Keyword, Name, String, Number, Generic
from pygments.util import shebang_matches


__all__ = ['Sp4Lexer']

line_re  = re.compile('.*?\n')


class Sp4Lexer(RegexLexer):
    name = 'SP4'
    aliases = ['sp4']
    filenames = ['*.sp4']
    mimetypes = ['text/x-sp4']

    flags = re.IGNORECASE
    tokens = {
        'root': [
            (r'\s+', Text),
            (r'--.*?\n', Comment.Single),
            (r'/\*', Comment.Multiline, 'multiline-comments'),
            (r'(ABORT|ABS|ABSOLUTE|ACCESS|ADA|ADD|ADMIN|AFTER|AGGREGATE|'
             r'ALIAS|ALL|ALLOCATE|ALTER|ANALYSE|ANALYZE|AND|ANY|ARE|AS|'
             r'ASC|ASENSITIVE|ASSERTION|ASSIGNMENT|ASYMMETRIC|AT|ATOMIC|'
             r'AUTHORIZATION|AVG|BACKWARD|BEFORE|BEGIN|BETWEEN|BITVAR|'
             r'BIT_LENGTH|BOTH|BREADTH|BY|C|CACHE|CALL|CALLED|CARDINALITY|'
             r'CASCADE|CASCADED|CASE|CAST|CATALOG|CATALOG_NAME|CHAIN|'
             r'CHARACTERISTICS|CHARACTER_LENGTH|CHARACTER_SET_CATALOG|'
             r'CHARACTER_SET_NAME|CHARACTER_SET_SCHEMA|CHAR_LENGTH|CHECK|'
             r'CHECKED|CHECKPOINT|CLASS|CLASS_ORIGIN|CLOB|CLOSE|CLUSTER|'
             r'COALSECE|COBOL|COLLATE|COLLATION|COLLATION_CATALOG|'
             r'COLLATION_NAME|COLLATION_SCHEMA|COLUMN|COLUMN_NAME|'
             r'COMMAND_FUNCTION|COMMAND_FUNCTION_CODE|COMMENT|COMMIT|'
             r'COMMITTED|COMPLETION|CONDITION_NUMBER|CONNECT|CONNECTION|'
             r'CONNECTION_NAME|CONSTRAINT|CONSTRAINTS|CONSTRAINT_CATALOG|'
             r'CONSTRAINT_NAME|CONSTRAINT_SCHEMA|CONSTRUCTOR|CONTAINS|'
             r'CONTINUE|CONVERSION|CONVERT|COPY|CORRESPONTING|COUNT|'
             r'CREATE|CREATEDB|CREATEUSER|CROSS|CUBE|CURRENT|CURRENT_DATE|'
             r'CURRENT_PATH|CURRENT_ROLE|CURRENT_TIME|CURRENT_TIMESTAMP|'
             r'CURRENT_USER|CURSOR|CURSOR_NAME|CYCLE|DATA|DATABASE|'
             r'DATETIME_INTERVAL_CODE|DATETIME_INTERVAL_PRECISION|DAY|'
             r'DEALLOCATE|DECLARE|DEFAULT|DEFAULTS|DEFERRABLE|DEFERRED|'
             r'DEFINED|DEFINER|DELETE|DELIMITER|DELIMITERS|DEREF|DESC|'
             r'DESCRIBE|DESCRIPTOR|DESTROY|DESTRUCTOR|DETERMINISTIC|'
             r'DIAGNOSTICS|DICTIONARY|DISCONNECT|DISPATCH|DISTINCT|DO|'
             r'DOMAIN|DROP|DYNAMIC|DYNAMIC_FUNCTION|DYNAMIC_FUNCTION_CODE|'
             r'EACH|ELSE|ENCODING|ENCRYPTED|END|END-EXEC|EQUALS|ESCAPE|EVERY|'
             r'EXCEPT|ESCEPTION|EXCLUDING|EXCLUSIVE|EXEC|EXECUTE|EXISTING|'
             r'EXISTS|EXPLAIN|EXTERNAL|EXTRACT|FALSE|FETCH|FINAL|FIRST|FOR|'
             r'FORCE|FOREIGN|FORTRAN|FORWARD|FOUND|FREE|FREEZE|FROM|FULL|'
             r'FUNCTION|G|GENERAL|GENERATED|GET|GLOBAL|GO|GOTO|GRANT|GRANTED|'
             r'GROUP|GROUPING|HANDLER|HAVING|HIERARCHY|HOLD|HOST|IDENTITY|'
             r'IGNORE|ILIKE|IMMEDIATE|IMMUTABLE|IMPLEMENTATION|IMPLICIT|IN|'
             r'INCLUDING|INCREMENT|INDEX|INDITCATOR|INFIX|INHERITS|INITIALIZE|'
             r'INITIALLY|INNER|INOUT|INPUT|INSENSITIVE|INSERT|INSTANTIABLE|'
             r'INSTEAD|INTERSECT|INTO|INVOKER|IS|ISNULL|ISOLATION|ITERATE|JOIN|'
             r'K|KEY|KEY_MEMBER|KEY_TYPE|LANCOMPILER|LANGUAGE|LARGE|LAST|'
             r'LATERAL|LEADING|LEFT|LENGTH|LESS|LEVEL|LIKE|LILMIT|LISTEN|LOAD|'
             r'LOCAL|LOCALTIME|LOCALTIMESTAMP|LOCATION|LOCATOR|LOCK|LOWER|M|'
             r'MAP|MATCH|MAX|MAXVALUE|MESSAGE_LENGTH|MESSAGE_OCTET_LENGTH|'
             r'MESSAGE_TEXT|METHOD|MIN|MINUTE|MINVALUE|MOD|MODE|MODIFIES|'
             r'MODIFY|MONTH|MORE|MOVE|MUMPS|NAMES|NATIONAL|NATURAL|NCHAR|'
             r'NCLOB|NEW|NEXT|NO|NOCREATEDB|NOCREATEUSER|NONE|NOT|NOTHING|'
             r'NOTIFY|NOTNULL|NULL|NULLABLE|NULLIF|OBJECT|OCTET_LENGTH|OF|OFF|'
             r'OFFSET|OIDS|OLD|ON|ONLY|OPEN|OPERATION|OPERATOR|OPTION|OPTIONS|'
             r'OR|ORDER|ORDINALITY|OUT|OUTER|OUTPUT|OVERLAPS|OVERLAY|OVERRIDING|'
             r'OWNER|PAD|PARAMETER|PARAMETERS|PARAMETER_MODE|PARAMATER_NAME|'
             r'PARAMATER_ORDINAL_POSITION|PARAMETER_SPECIFIC_CATALOG|'
             r'PARAMETER_SPECIFIC_NAME|PARAMATER_SPECIFIC_SCHEMA|PARTIAL|'
             r'PASCAL|PENDANT|PLACING|PLI|POSITION|POSTFIX|PRECISION|PREFIX|'
             r'PREORDER|PREPARE|PRESERVE|PRIMARY|PRIOR|PRIVILEGES|PROCEDURAL|'
             r'PROCEDURE|PUBLIC|READ|READS|RECHECK|RECURSIVE|REF|REFERENCES|'
             r'REFERENCING|REINDEX|RELATIVE|RENAME|REPEATABLE|REPLACE|RESET|'
             r'RESTART|RESTRICT|RESULT|RETURN|RETURNED_LENGTH|'
             r'RETURNED_OCTET_LENGTH|RETURNED_SQLSTATE|RETURNS|REVOKE|RIGHT|'
             r'ROLE|ROLLBACK|ROLLUP|ROUTINE|ROUTINE_CATALOG|ROUTINE_NAME|'
             r'ROUTINE_SCHEMA|ROW|ROWS|ROW_COUNT|RULE|SAVE_POINT|SCALE|SCHEMA|'
             r'SCHEMA_NAME|SCOPE|SCROLL|SEARCH|SECOND|SECURITY|SELECT|SELF|'
             r'SENSITIVE|SERIALIZABLE|SERVER_NAME|SESSION|SESSION_USER|SET|'
             r'SETOF|SETS|SHARE|SHOW|SIMILAR|SIMPLE|SIZE|SOME|SOURCE|SPACE|'
             r'SPECIFIC|SPECIFICTYPE|SPECIFIC_NAME|SQL|SQLCODE|SQLERROR|'
             r'SQLEXCEPTION|SQLSTATE|SQLWARNINIG|STABLE|START|STATE|STATEMENT|'
             r'STATIC|STATISTICS|STDIN|STDOUT|STORAGE|STRICT|STRUCTURE|STYPE|'
             r'SUBCLASS_ORIGIN|SUBLIST|SUBSTRING|SUM|SYMMETRIC|SYSID|SYSTEM|'
             r'SYSTEM_USER|TABLE|TABLE_NAME| TEMP|TEMPLATE|TEMPORARY|TERMINATE|'
             r'THAN|THEN|TIMESTAMP|TIMEZONE_HOUR|TIMEZONE_MINUTE|TO|TOAST|'
             r'TRAILING|TRANSATION|TRANSACTIONS_COMMITTED|'
             r'TRANSACTIONS_ROLLED_BACK|TRANSATION_ACTIVE|TRANSFORM|'
             r'TRANSFORMS|TRANSLATE|TRANSLATION|TREAT|TRIGGER|TRIGGER_CATALOG|'
             r'TRIGGER_NAME|TRIGGER_SCHEMA|TRIM|TRUE|TRUNCATE|TRUSTED|TYPE|'
             r'UNCOMMITTED|UNDER|UNENCRYPTED|UNION|UNIQUE|UNKNOWN|UNLISTEN|'
             r'UNNAMED|UNNEST|UNTIL|UPDATE|UPPER|USAGE|USER|'
             r'USER_DEFINED_TYPE_CATALOG|USER_DEFINED_TYPE_NAME|'
             r'USER_DEFINED_TYPE_SCHEMA|USING|VACUUM|VALID|VALIDATOR|VALUES|'
             r'VARIABLE|VERBOSE|VERSION|VIEW|VOLATILE|WHEN|WHENEVER|WHERE|'
             r'WITH|WITHOUT|WORK|WRITE|YEAR|ZONE|BINARY_INTEGER|BODY|BREAK|'
             r'CONSTANT|DEFINITION|DELETING|DLOB|DUMMY|ELSIF|ERRLVL|ERROR|'
             r'EXCEPTION|EXIT|IF|INSERTING|ISOPEN|LOOP|NO_DATA_FOUND|NOTFOUND|'
             r'OTHERS|PACKAGE|PRAGMA|RAISE|RECORD|RESTRICT_REFERENCES|RETURNING|'
             r'RNDS|RNPS|ROWCOUNT|ROWNUM|ROWTYPE|SAVEPOINT|SQLERRM|TOO_MANY_ROWS|'
             r'UPDATING|WHILE|WNDS|WNPS|BULK|CHR|COLLECT|GREATEST|INSTR|LEAST|'
             r'LENGTHB|NOCOPY|NOWAIT|NVL|RPAD|SUBST|SUBSTB|SUBSTR|SYSDATE|'
             r'TABLESPACE|TO_CHAR|TO_DATE|TO_NUMBER|TRUNC)\b', Keyword),
            (r'(ARRAY|BIGINT|BINARY|BIT|BLOB|BOOLEAN|CHAR|CHARACTER|DATE|'
             r'DEC|DECIMAL|FLOAT|INT|INTEGER|INTERVAL|NUMBER|NUMERIC|REAL|'
             r'SERIAL|SMALLINT|VARCHAR|VARCHAR2|VARYING|INT8|SERIAL8|TEXT)\b',
             Name.Builtin),
            (r'(_5date_args|_actual_area|_ASSERT|_doc_code|_doc_var|_doc_var_list|'
             r'_enforce|_ent|_enum|_enums_define|_enums_member_define|_field|'
             r'_fields|_first|_FMT|_in_list|_index|_index_unique|_indexes'
             r'_MAX_STRLEN|_MID_STRLEN|_param|_package|_pk|_plsql_param|_plsql_return|'
             r'_private_function|_private_procedure|_private_type|_private_var|'
             r'_protected_function|_protected_procedure|_protected_type|_protected_var|'
             r'_public_function|_public_procedure|_public_type|_public_var|_quote|_RAISE|'
             r'_RAISEW|_reference|_references|_request_arg|_request_define|'
             r'_request_res|_STR_CONST|_substr|_table|_tail|builtin|cdr|changecom|'
             r'changequote|changeword|debugfile|decr|define|divert|dummy_list|dumpdef|'
             r'errprint|eval|foreach|forloop|GetNth|ifelse|include|incr|index|indir|'
             r'len|lowcase|maketemp|Nth|patsubst|popdef|pushdef|regexp|'
             r'remove_prefix|shift|sinclude|Size|syscmd|TRACE|traceoff|traceon|'
             r'translit|undefine|undivert|upcase)\b',
             Name.Function),
            (r'[+*/<>=~!@#%^&|`?^-]', Operator),
            (r'[0-9]+', Number.Integer),
            (r"'(''|[^'\\]|\\\'|\\\\)*'", String.Single),
            (r'"(""|[^"\\]|\\\"|\\\\)*"', String.Symbol),
            (r'[a-zA-Z_][a-zA-Z0-9_]*', Name),
            (r'[;:()\[\],\.]', Punctuation)
        ],
        'multiline-comments': [
            (r'/\*', Comment.Multiline, 'multiline-comments'),
            (r'\*/', Comment.Multiline, '#pop'),
            (r'[^/\*]+', Comment.Multiline),
            (r'[/*]', Comment.Multiline)
        ]
    }
